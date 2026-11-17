"""Reglas del inicio de sesión (CU-01, sección 8.2 de la arquitectura).

El bloqueo por intentos fallidos, el límite por IP y el registro de los
intentos fallidos en la bitácora se agregan en el PR 1.3.
"""

from dataclasses import dataclass
from enum import StrEnum

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar
from apps.core.errores import ErrorApi

from .managers import normalizar_correo
from .models import Rol, Usuario
from .tokens import Alcance, alcance_tras_la_contrasena


class Paso(StrEnum):
    """Qué debe hacer el navegador después de enviar correo y contraseña."""

    LISTO = "listo"
    MFA = "mfa"
    ENROLAR_MFA = "enrolar_mfa"


@dataclass(frozen=True)
class ResultadoLogin:
    usuario: Usuario
    paso: Paso
    # Alcance de la sesión que corresponde emitir; ``None`` si no corresponde ninguna.
    alcance: Alcance | None


# El paso que ve el navegador sale siempre del alcance, nunca al revés.
_PASO_POR_ALCANCE = {
    Alcance.COMPLETA: Paso.LISTO,
    Alcance.ENROLAR_MFA: Paso.ENROLAR_MFA,
    None: Paso.MFA,
}


def _credenciales_invalidas() -> ErrorApi:
    # El mismo error si el correo no existe, si la cuenta está desactivada o
    # si la contraseña no coincide: la respuesta no revela cuál fue el caso.
    return ErrorApi(
        "credenciales_invalidas",
        "Correo o contraseña incorrectos",
        estado=status.HTTP_401_UNAUTHORIZED,
    )


def _sin_consentimiento() -> ErrorApi:
    # Ley 21.719: la cuenta de un alumno no se usa hasta que el administrador
    # registre que el colegio tiene el consentimiento del apoderado.
    return ErrorApi(
        "cuenta_no_habilitada",
        "Tu cuenta aún no está habilitada. Consulta en el colegio.",
        estado=status.HTTP_403_FORBIDDEN,
    )


@transaction.atomic
def iniciar_sesion(*, correo: str, password: str, peticion=None) -> ResultadoLogin:
    """Comprueba las credenciales y decide el paso siguiente.

    No emite tokens: eso lo hace la vista con el alcance que resulte. Un
    docente o administrador nunca sale de aquí con una sesión completa: o
    queda restringido a enrolar su 2FA, o debe verificar el segundo factor.
    """
    usuario = Usuario.objects.filter(correo=normalizar_correo(correo), is_active=True).first()
    if usuario is None or not usuario.check_password(password):
        raise _credenciales_invalidas()

    # Solo después de comprobar la contraseña: así este mensaje no le confirma
    # a un extraño que el correo existe.
    if usuario.rol == Rol.ALUMNO and not usuario.tiene_consentimiento:
        raise _sin_consentimiento()

    alcance = alcance_tras_la_contrasena(usuario)
    if alcance is Alcance.COMPLETA:
        usuario.ultimo_acceso = timezone.now()
        usuario.save(update_fields=["ultimo_acceso"])
        registrar(Accion.LOGIN_OK, actor=usuario, peticion=peticion)
    elif alcance is Alcance.ENROLAR_MFA:
        # Queda constancia de que la sesión emitida no es completa.
        registrar(
            Accion.LOGIN_OK,
            actor=usuario,
            peticion=peticion,
            detalle={"sesion": "restringida", "pendiente": "enrolar_mfa"},
        )
    return ResultadoLogin(usuario=usuario, paso=_PASO_POR_ALCANCE[alcance], alcance=alcance)
