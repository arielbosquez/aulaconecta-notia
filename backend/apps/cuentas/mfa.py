"""Segundo factor TOTP para docentes y administradores (CU-02, RS-06).

El secreto se genera en el servidor y el QR también: el navegador recibe el
QR ya dibujado (SVG en una URI ``data:``) y lo muestra con una etiqueta
``<img>``, sin insertar HTML.
"""

import hmac
import logging
import secrets
import time
from dataclasses import dataclass

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar
from apps.core.errores import ErrorApi

from .models import CodigoRecuperacion, Usuario

registro = logging.getLogger(__name__)

# Nombre con que la cuenta aparece en la aplicación de autenticación.
EMISOR = "NotIA · AulaConecta"
# Códigos de 6 dígitos que cambian cada 30 segundos (los valores estándar).
DIGITOS = 6
INTERVALO = 30

# Códigos de recuperación: 8 de un solo uso, de 10 caracteres, sin letras ni
# números que se confundan al copiarlos a mano (0/O, 1/I/L).
CANTIDAD_DE_CODIGOS = 8
ALFABETO_RECUPERACION = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO_RECUPERACION = 10

# Firma del ticket del paso intermedio (TimestampSigner con SECRET_KEY).
SAL_TICKET = "notia.cuentas.ticket_mfa"


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


def totp_de(secreto: str) -> pyotp.TOTP:
    return pyotp.TOTP(secreto, digits=DIGITOS, interval=INTERVALO)


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


# --- Enrolamiento -------------------------------------------------------------


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
    incluidas); la vista entrega a este navegador una sesión completa. Se
    crean los 8 códigos de recuperación y quedan en ``cuenta.codigos_nuevos``
    para mostrarlos una sola vez.

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
    cuenta.codigos_nuevos = _crear_codigos_de_recuperacion(cuenta)
    registrar(
        Accion.MFA_ACTIVADO,
        actor=cuenta,
        peticion=peticion,
        detalle={"recuperacion_entregados": CANTIDAD_DE_CODIGOS},
    )
    return cuenta


# --- Códigos de recuperación ----------------------------------------------------


def _normalizar_recuperacion(codigo: str) -> str:
    return "".join(codigo.upper().split()).replace("-", "")


def _nuevo_codigo_de_recuperacion() -> str:
    crudo = "".join(secrets.choice(ALFABETO_RECUPERACION) for _ in range(LARGO_RECUPERACION))
    mitad = LARGO_RECUPERACION // 2
    return f"{crudo[:mitad]}-{crudo[mitad:]}"


def _crear_codigos_de_recuperacion(cuenta: Usuario) -> list[str]:
    """Reemplaza los códigos de la cuenta por 8 nuevos y los devuelve en texto.

    Es la única vez que existen en texto: se guardan con hash Argon2id.
    """
    CodigoRecuperacion.objects.filter(usuario=cuenta).delete()
    codigos = [_nuevo_codigo_de_recuperacion() for _ in range(CANTIDAD_DE_CODIGOS)]
    CodigoRecuperacion.objects.bulk_create(
        CodigoRecuperacion(usuario=cuenta, codigo_hash=make_password(_normalizar_recuperacion(c)))
        for c in codigos
    )
    return codigos


def _usar_codigo_de_recuperacion(cuenta: Usuario, codigo: str) -> int | None:
    """Gasta el código si es uno de los vigentes. Devuelve cuántos quedan, o ``None``.

    Quien llama tiene la fila del usuario bloqueada, así que dos peticiones
    con el mismo código no pueden gastarlo las dos.
    """
    normalizado = _normalizar_recuperacion(codigo)
    if len(normalizado) != LARGO_RECUPERACION:
        return None
    vigentes = list(CodigoRecuperacion.objects.filter(usuario=cuenta, usado_en__isnull=True))
    for guardado in vigentes:
        if check_password(normalizado, guardado.codigo_hash):
            guardado.usado_en = timezone.now()
            guardado.save(update_fields=["usado_en"])
            return len(vigentes) - 1
    return None


# --- Ticket del paso intermedio -------------------------------------------------


@dataclass(frozen=True)
class Ticket:
    usuario: Usuario
    # Identificador al azar del ticket: para el límite de intentos y para que
    # sirva una sola vez.
    numero: str


def emitir_ticket(usuario: Usuario) -> str:
    """Ticket firmado que prueba que la contraseña fue correcta hace menos de 5 minutos.

    No es una sesión: solo sirve para enviar el código del segundo factor.
    Lleva ``version_sesion``, así que un cambio de contraseña lo invalida.
    """
    datos = {"u": str(usuario.pk), "v": usuario.version_sesion, "n": secrets.token_urlsafe(16)}
    return signing.TimestampSigner(salt=SAL_TICKET).sign_object(datos)


def _marca_de_ticket_usado(numero: str) -> str:
    return f"ticket_mfa_usado:{numero}"


def _datos_del_ticket(valor: str | None) -> dict | None:
    if not valor:
        return None
    try:
        datos = signing.TimestampSigner(salt=SAL_TICKET).unsign_object(
            valor, max_age=settings.MFA_DURACION_DEL_TICKET
        )
    except signing.BadSignature:
        # Incluye un ticket vencido (SignatureExpired).
        return None
    if not isinstance(datos, dict) or not isinstance(datos.get("n"), str):
        return None
    return datos


def numero_de_ticket(valor: str | None) -> str | None:
    """Número de un ticket auténtico y vigente, sin consultar la base (para el límite)."""
    datos = _datos_del_ticket(valor)
    return datos["n"] if datos else None


def leer_ticket(valor: str | None) -> Ticket | None:
    """Devuelve el ticket si es auténtico, vigente, no usado y de una cuenta que lo admite."""
    datos = _datos_del_ticket(valor)
    if datos is None or cache.get(_marca_de_ticket_usado(datos["n"])):
        return None
    try:
        usuario = Usuario.objects.get(pk=datos.get("u"), is_active=True)
    except (Usuario.DoesNotExist, ValueError, TypeError, ValidationError):
        return None
    if usuario.version_sesion != datos.get("v") or not usuario.mfa_habilitado:
        return None
    return Ticket(usuario=usuario, numero=datos["n"])


def ticket_invalido() -> ErrorApi:
    return ErrorApi(
        "ticket_invalido",
        "Tu inicio de sesión venció. Vuelve a ingresar tu correo y contraseña.",
        estado=status.HTTP_401_UNAUTHORIZED,
    )


# --- Verificación (CU-02) -------------------------------------------------------


@dataclass(frozen=True)
class Verificacion:
    usuario: Usuario
    metodo: str
    codigos_restantes: int | None


def verificar_segundo_factor(ticket: Ticket, codigo: str, *, peticion=None) -> Verificacion:
    """Comprueba el código del TOTP o un código de recuperación.

    - Cada código incorrecto suma al mismo contador de intentos que el login
      (con 5 la cuenta se bloquea 15 minutos), además del límite de 5
      intentos cada 5 minutos por ticket.
    - Durante el bloqueo el código no se compara: responde el mismo error que
      un código incorrecto, para no servir de oráculo.
    - Si el código sirve, el ticket queda gastado.
    """
    # Se importa aquí para evitar un ciclo: servicios importa este módulo.
    from .servicios import _reiniciar_intentos, contar_intento_fallido

    usuario = ticket.usuario
    if usuario.esta_bloqueado():
        registrar(
            Accion.MFA_FALLIDO,
            peticion=peticion,
            objeto=usuario,
            detalle={"motivo": "cuenta_bloqueada"},
        )
        raise _codigo_invalido()

    resultado = _comprobar(usuario, codigo, peticion)
    if resultado is None:
        contar_intento_fallido(
            usuario, peticion=peticion, motivo="codigo_incorrecto", accion=Accion.MFA_FALLIDO
        )
        raise _codigo_invalido()

    # El ticket sirve una sola vez: la marca dura lo mismo que el ticket.
    cache.set(
        _marca_de_ticket_usado(ticket.numero),
        True,
        timeout=int(settings.MFA_DURACION_DEL_TICKET.total_seconds()),
    )
    _reiniciar_intentos(usuario)
    return resultado


@transaction.atomic
def _comprobar(usuario: Usuario, codigo: str, peticion) -> Verificacion | None:
    cuenta = Usuario.objects.select_for_update().get(pk=usuario.pk)
    paso = paso_del_codigo(cuenta, codigo)
    if paso is not None:
        cuenta.mfa_ultimo_paso = paso
        metodo, restantes = "totp", None
    else:
        restantes = _usar_codigo_de_recuperacion(cuenta, codigo)
        if restantes is None:
            return None
        metodo = "recuperacion"
    cuenta.ultimo_acceso = timezone.now()
    cuenta.save(update_fields=["mfa_ultimo_paso", "ultimo_acceso"])
    detalle = {"metodo": metodo}
    if restantes is not None:
        detalle["recuperacion_restantes"] = restantes
    registrar(Accion.MFA_OK, actor=cuenta, peticion=peticion, detalle=detalle)
    return Verificacion(usuario=cuenta, metodo=metodo, codigos_restantes=restantes)
