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


class Paso(StrEnum):
    """Qué debe hacer el navegador después de enviar correo y contraseña."""

    LISTO = "listo"
    MFA = "mfa"
    ENROLAR_MFA = "enrolar_mfa"


@dataclass(frozen=True)
class ResultadoLogin:
    usuario: Usuario
    paso: Paso


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


def _paso_siguiente(usuario: Usuario) -> Paso:
    """Docentes y administradores nunca quedan listos solo con la contraseña."""
    if not usuario.es_del_personal:
        return Paso.LISTO
    return Paso.MFA if usuario.mfa_habilitado else Paso.ENROLAR_MFA


@transaction.atomic
def iniciar_sesion(*, correo: str, password: str, peticion=None) -> ResultadoLogin:
    """Comprueba las credenciales y decide el paso siguiente.

    No emite tokens: eso lo hace la vista según el paso que resulte.
    """
    usuario = Usuario.objects.filter(correo=normalizar_correo(correo), is_active=True).first()
    if usuario is None or not usuario.check_password(password):
        raise _credenciales_invalidas()

    # Solo después de comprobar la contraseña: así este mensaje no le confirma
    # a un extraño que el correo existe.
    if usuario.rol == Rol.ALUMNO and not usuario.tiene_consentimiento:
        raise _sin_consentimiento()

    paso = _paso_siguiente(usuario)
    if paso is Paso.LISTO:
        usuario.ultimo_acceso = timezone.now()
        usuario.save(update_fields=["ultimo_acceso"])
        registrar(Accion.LOGIN_OK, actor=usuario, peticion=peticion)
    return ResultadoLogin(usuario=usuario, paso=paso)
