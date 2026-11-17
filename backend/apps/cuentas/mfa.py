"""Segundo factor TOTP para docentes y administradores (CU-02, RS-06).

El secreto se genera en el servidor y el QR también: el navegador recibe el
QR ya dibujado (SVG en una URI ``data:``) y lo muestra con una etiqueta
``<img>``, sin insertar HTML.
"""

import hmac
import logging
import time

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from rest_framework import status

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar
from apps.core.errores import ErrorApi

from .models import Usuario

registro = logging.getLogger(__name__)

# Nombre con que la cuenta aparece en la aplicación de autenticación.
EMISOR = "NotIA · AulaConecta"
# Códigos de 6 dígitos que cambian cada 30 segundos (los valores estándar).
DIGITOS = 6
INTERVALO = 30


def _ya_activado() -> ErrorApi:
    return ErrorApi(
        "mfa_ya_activado",
        "El segundo factor ya está activado. Para cambiarlo, pide al colegio que lo reinicie.",
        estado=status.HTTP_409_CONFLICT,
    )


def _cambiar_password_primero() -> ErrorApi:
    # Una contraseña temporal la conoce también quien creó la cuenta: el 2FA
    # se enrola solo cuando la contraseña es de la persona.
    return ErrorApi(
        "cambiar_password_primero",
        "Antes de activar el segundo factor, cambia tu contraseña temporal.",
        estado=status.HTTP_403_FORBIDDEN,
    )


def _solo_personal() -> ErrorApi:
    return ErrorApi(
        "sin_permiso",
        "No tienes permiso para realizar esta acción.",
        estado=status.HTTP_403_FORBIDDEN,
    )


def totp_de(secreto: str) -> pyotp.TOTP:
    return pyotp.TOTP(secreto, digits=DIGITOS, interval=INTERVALO)


def _codigo_invalido() -> ErrorApi:
    return ErrorApi(
        "codigo_invalido",
        "El código no es válido o ya se usó. Espera el siguiente e inténtalo de nuevo.",
        estado=status.HTTP_400_BAD_REQUEST,
    )


def _mfa_no_disponible() -> ErrorApi:
    return ErrorApi(
        "mfa_no_disponible",
        "No pudimos comprobar tu segundo factor. Pide ayuda en el colegio.",
        estado=status.HTTP_409_CONFLICT,
    )


def _fernet() -> Fernet:
    return Fernet(settings.MFA_ENCRYPTION_KEY)


def guardar_secreto(usuario: Usuario, secreto: str) -> None:
    """Guarda el secreto TOTP cifrado con Fernet (``MFA_ENCRYPTION_KEY``).

    Fernet cifra con AES y autentica con HMAC: quien lea la base de datos sin
    la llave no obtiene el secreto ni puede alterarlo sin que se note.
    """
    usuario.mfa_secreto_cifrado = _fernet().encrypt(secreto.encode("ascii")).decode("ascii")


def leer_secreto(usuario: Usuario) -> str:
    """Descifra el secreto TOTP. Si no se puede, el 2FA de la cuenta queda inutilizable."""
    try:
        return _fernet().decrypt(usuario.mfa_secreto_cifrado.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError) as error:
        # Llave cambiada o dato alterado. Nunca se registra el contenido.
        registro.error("No se pudo descifrar el secreto 2FA de una cuenta")
        raise _mfa_no_disponible() from error


def paso_del_codigo(cuenta: Usuario, codigo: str, *, ahora: float | None = None) -> int | None:
    """Devuelve el intervalo TOTP al que corresponde ``codigo``, o ``None``.

    Acepta el intervalo actual y uno a cada lado (relojes desfasados hasta
    30 segundos). Rechaza un código de un intervalo ya usado o anterior
    (``mfa_ultimo_paso``): un código visto por encima del hombro, o enviado
    dos veces, no sirve de nuevo. Quien llama debe tener la fila bloqueada.
    """
    if len(codigo) != DIGITOS or not codigo.isdigit():
        return None
    totp = totp_de(leer_secreto(cuenta))
    momento = time.time() if ahora is None else ahora
    for desfase in (-1, 0, 1):
        instante = momento + desfase * INTERVALO
        if hmac.compare_digest(totp.at(instante), codigo):
            paso = int(instante // INTERVALO)
            if cuenta.mfa_ultimo_paso is not None and paso <= cuenta.mfa_ultimo_paso:
                return None
            return paso
    return None


def qr_como_data_uri(uri: str) -> str:
    """Dibuja el QR en el servidor y lo devuelve como ``data:image/svg+xml``."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#1b1f2a")


@transaction.atomic
def iniciar_enrolamiento(usuario: Usuario) -> dict:
    """Genera un secreto nuevo, pendiente de confirmar, y su QR.

    Mientras no se confirme con un código, el 2FA no queda activado. Volver a
    pedirlo reemplaza el secreto pendiente: el QR anterior deja de servir.
    """
    if not usuario.es_del_personal:
        raise _solo_personal()
    cuenta = Usuario.objects.select_for_update().get(pk=usuario.pk)
    if cuenta.mfa_habilitado:
        raise _ya_activado()
    if cuenta.debe_cambiar_password:
        raise _cambiar_password_primero()

    secreto = pyotp.random_base32()
    guardar_secreto(cuenta, secreto)
    cuenta.mfa_ultimo_paso = None
    cuenta.save(update_fields=["mfa_secreto_cifrado", "mfa_ultimo_paso"])

    uri = totp_de(secreto).provisioning_uri(name=cuenta.correo, issuer_name=EMISOR)
    return {
        "qr": qr_como_data_uri(uri),
        # Para escribirlo a mano si el teléfono no puede leer el QR.
        "secreto": secreto,
        "digitos": DIGITOS,
        "intervalo": INTERVALO,
    }


def confirmar_enrolamiento(usuario: Usuario, codigo: str, *, peticion=None) -> Usuario:
    """Activa el 2FA si el código corresponde al secreto pendiente.

    Al activarlo se cierran todas las sesiones de la cuenta (las restringidas
    incluidas); la vista entrega a este navegador una sesión completa.

    El fallo se registra fuera de la transacción: si no, el error la desharía
    y el registro se perdería.
    """
    cuenta = _activar_si_el_codigo_sirve(usuario, codigo, peticion)
    if cuenta is None:
        registrar(
            Accion.MFA_FALLIDO, actor=usuario, peticion=peticion, detalle={"etapa": "enrolamiento"}
        )
        raise _codigo_invalido()
    return cuenta


@transaction.atomic
def _activar_si_el_codigo_sirve(usuario: Usuario, codigo: str, peticion) -> Usuario | None:
    if not usuario.es_del_personal:
        raise _solo_personal()
    # Fila bloqueada: dos confirmaciones simultáneas con el mismo código no
    # pueden pasar las dos (la segunda ve el intervalo ya usado).
    cuenta = Usuario.objects.select_for_update().get(pk=usuario.pk)
    if cuenta.mfa_habilitado:
        raise _ya_activado()
    if cuenta.debe_cambiar_password:
        raise _cambiar_password_primero()
    if not cuenta.mfa_secreto_cifrado:
        raise ErrorApi(
            "enrolamiento_no_iniciado",
            "Primero pide el código QR para activar el segundo factor.",
            estado=status.HTTP_409_CONFLICT,
        )

    paso = paso_del_codigo(cuenta, codigo)
    if paso is None:
        return None
    cuenta.mfa_habilitado = True
    cuenta.mfa_ultimo_paso = paso
    cuenta.cerrar_todas_las_sesiones()
    cuenta.save(update_fields=["mfa_habilitado", "mfa_ultimo_paso", "version_sesion"])
    registrar(Accion.MFA_ACTIVADO, actor=cuenta, peticion=peticion)
    return cuenta
