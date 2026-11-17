"""Emisión y validación de los tokens de sesión (RS-04).

Cada sesión son dos JWT firmados con ``JWT_SIGNING_KEY``: uno de acceso, de
5 minutos, y uno de refresco, de 8 horas. Ambos llevan el claim ``ver`` con
la ``version_sesion`` del usuario al emitirlos. Si ese número ya no coincide
con el de la base de datos, el token se rechaza: así cambiar la contraseña o
desactivar una cuenta cierra todas sus sesiones de inmediato.

Los tokens solo viajan en cookies (ver ``cookies.py``); nunca se entregan en
el cuerpo de una respuesta.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token

from .models import Usuario

CLAIM_VERSION = "ver"


@dataclass(frozen=True)
class TokensDeSesion:
    acceso: str
    refresco: str


def emitir_tokens(usuario: Usuario) -> TokensDeSesion:
    """Crea un par de tokens nuevo para el usuario."""
    refresco = RefreshToken.for_user(usuario)
    refresco[CLAIM_VERSION] = usuario.version_sesion
    # El token de acceso copia los claims del de refresco.
    return TokensDeSesion(acceso=str(refresco.access_token), refresco=str(refresco))


def usuario_del_token(token: Token) -> Usuario | None:
    """Devuelve el usuario dueño del token, o ``None`` si el token ya no vale.

    No vale si la cuenta no existe, está desactivada o cerró sus sesiones
    después de emitirlo.
    """
    identificador = token.get(api_settings.USER_ID_CLAIM)
    version = token.get(CLAIM_VERSION)
    if not identificador or not isinstance(version, int) or isinstance(version, bool):
        return None
    try:
        usuario = Usuario.objects.get(pk=identificador, is_active=True)
    except (Usuario.DoesNotExist, ValidationError, ValueError, TypeError):
        # ValidationError: el identificador no tiene forma de UUID.
        return None
    if usuario.version_sesion != version:
        return None
    return usuario
