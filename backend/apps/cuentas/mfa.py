"""Segundo factor TOTP para docentes y administradores (CU-02, RS-06).

El secreto se genera en el servidor y el QR también: el navegador recibe el
QR ya dibujado (SVG en una URI ``data:``) y lo muestra con una etiqueta
``<img>``, sin insertar HTML.
"""

import pyotp
import segno
from django.db import transaction
from rest_framework import status

from apps.core.errores import ErrorApi

from .models import Usuario

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


def guardar_secreto(usuario: Usuario, secreto: str) -> None:
    usuario.mfa_secreto_cifrado = secreto


def leer_secreto(usuario: Usuario) -> str:
    return usuario.mfa_secreto_cifrado


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
