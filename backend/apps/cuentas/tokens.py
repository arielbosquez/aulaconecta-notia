"""Emisión y validación de los tokens de sesión (RS-04).

Cada sesión son dos JWT firmados con ``JWT_SIGNING_KEY``: uno de acceso, de
5 minutos, y uno de refresco, de 8 horas. Ambos llevan dos claims propios:

- ``ver``: la ``version_sesion`` del usuario al emitirlos. Si ese número ya
  no coincide con el de la base de datos, el token se rechaza: así cambiar la
  contraseña o desactivar una cuenta cierra todas sus sesiones de inmediato.
- ``alc``: el alcance de la sesión. Una sesión completa da acceso a la
  aplicación; una restringida solo sirve para terminar un paso pendiente.

Los tokens solo viajan en cookies (ver ``cookies.py``); nunca se entregan en
el cuerpo de una respuesta.
"""

from dataclasses import dataclass
from enum import StrEnum

from django.core.exceptions import ValidationError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token

from .models import Usuario

CLAIM_VERSION = "ver"
CLAIM_ALCANCE = "alc"


class Alcance(StrEnum):
    """Qué permite hacer una sesión."""

    COMPLETA = "completa"
    # Docente o administrador que pasó la contraseña pero aún no activa su
    # segundo factor: solo puede consultar su estado y enrolar el 2FA.
    ENROLAR_MFA = "enrolar_mfa"


@dataclass(frozen=True)
class TokensDeSesion:
    acceso: str
    refresco: str


def alcance_tras_la_contrasena(usuario: Usuario) -> Alcance | None:
    """Alcance de la sesión que se emite apenas se comprueba la contraseña.

    - Alumno: sesión completa.
    - Docente o administrador sin 2FA activado: sesión restringida a enrolarlo.
    - Docente o administrador con 2FA: ninguna sesión (``None``) hasta que
      verifique el segundo factor.

    Solo con la contraseña, el personal nunca obtiene una sesión completa.
    """
    if not usuario.es_del_personal:
        return Alcance.COMPLETA
    if usuario.mfa_habilitado:
        return None
    return Alcance.ENROLAR_MFA


def emitir_tokens(usuario: Usuario, alcance: Alcance) -> TokensDeSesion:
    """Crea un par de tokens nuevo para el usuario con el alcance indicado."""
    refresco = RefreshToken.for_user(usuario)
    refresco[CLAIM_VERSION] = usuario.version_sesion
    refresco[CLAIM_ALCANCE] = Alcance(alcance).value
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


def alcance_vigente(usuario: Usuario, token: Token) -> Alcance | None:
    """Devuelve el alcance del token, o ``None`` si no corresponde a ese usuario.

    Segunda barrera: aunque un token diga "completa", no se acepta para un
    docente o administrador que no tiene el 2FA activado.
    """
    try:
        alcance = Alcance(token.get(CLAIM_ALCANCE))
    except ValueError:
        return None
    if alcance is Alcance.COMPLETA and usuario.es_del_personal and not usuario.mfa_habilitado:
        return None
    return alcance
