"""Reglas del inicio de sesión (CU-01, sección 8.2 de la arquitectura)."""

from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings
from django.db import transaction
from django.db.models import Q
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


@dataclass(frozen=True)
class IntentoFallido:
    """Cómo quedó la cuenta después de una contraseña incorrecta."""

    # Fallos seguidos que lleva la cuenta, contando este.
    intentos: int
    # ``True`` solo para la petición que dejó la cuenta bloqueada.
    bloqueo_iniciado: bool
    # ``True`` si otra petición la bloqueó mientras esta comprobaba la contraseña.
    ya_estaba_bloqueada: bool


# El paso que ve el navegador sale siempre del alcance, nunca al revés.
_PASO_POR_ALCANCE = {
    Alcance.COMPLETA: Paso.LISTO,
    Alcance.ENROLAR_MFA: Paso.ENROLAR_MFA,
    None: Paso.MFA,
}


def _credenciales_invalidas() -> ErrorApi:
    # El mismo error si el correo no existe, si la cuenta está desactivada, si
    # la contraseña no coincide o si la cuenta está bloqueada y la contraseña
    # no coincide: la respuesta no revela cuál fue el caso.
    return ErrorApi(
        "credenciales_invalidas",
        "Correo o contraseña incorrectos",
        estado=status.HTTP_401_UNAUTHORIZED,
    )


def _cuenta_bloqueada() -> ErrorApi:
    # Solo lo ve quien escribió la contraseña correcta: a un extraño no le
    # confirma que el correo existe ni que la cuenta está bloqueada.
    return ErrorApi(
        "cuenta_bloqueada",
        "Cuenta bloqueada temporalmente por varios intentos fallidos. "
        "Vuelve a intentarlo en 15 minutos o pide ayuda en el colegio.",
        estado=status.HTTP_423_LOCKED,
    )


def _sin_consentimiento() -> ErrorApi:
    # Ley 21.719: la cuenta de un alumno no se usa hasta que el administrador
    # registre que el colegio tiene el consentimiento del apoderado.
    return ErrorApi(
        "cuenta_no_habilitada",
        "Tu cuenta aún no está habilitada. Consulta en el colegio.",
        estado=status.HTTP_403_FORBIDDEN,
    )


def _sin_bloqueo_vigente(ahora) -> Q:
    return Q(bloqueado_hasta__isnull=True) | Q(bloqueado_hasta__lte=ahora)


@transaction.atomic
def contar_intento_fallido(usuario: Usuario) -> IntentoFallido:
    """Suma una contraseña incorrecta a la cuenta y la bloquea al llegar al límite.

    Es a prueba de peticiones simultáneas: la fila del usuario se bloquea
    (``SELECT … FOR UPDATE``) y el contador se lee de la base, no del objeto
    que la petición cargó antes de comprobar la contraseña. Así, si llegan
    varias contraseñas incorrectas a la vez, cada una suma la suya y solo una
    de ellas bloquea la cuenta.

    Al bloquear, el contador vuelve a cero: cuando el bloqueo vence, la cuenta
    tiene de nuevo 5 intentos.
    """
    fila = Usuario.objects.select_for_update().values("intentos_fallidos", "bloqueado_hasta")
    actual = fila.get(pk=usuario.pk)
    ahora = timezone.now()

    if actual["bloqueado_hasta"] is not None and actual["bloqueado_hasta"] > ahora:
        # Otra petición la bloqueó mientras esta calculaba el hash. El
        # bloqueo ya corre: este intento no lo alarga ni suma.
        return IntentoFallido(
            intentos=actual["intentos_fallidos"], bloqueo_iniciado=False, ya_estaba_bloqueada=True
        )

    intentos = actual["intentos_fallidos"] + 1
    if intentos >= settings.LOGIN_INTENTOS_ANTES_DE_BLOQUEAR:
        Usuario.objects.filter(pk=usuario.pk).update(
            intentos_fallidos=0, bloqueado_hasta=ahora + settings.LOGIN_DURACION_DEL_BLOQUEO
        )
        return IntentoFallido(intentos=intentos, bloqueo_iniciado=True, ya_estaba_bloqueada=False)

    Usuario.objects.filter(pk=usuario.pk).update(intentos_fallidos=intentos)
    return IntentoFallido(intentos=intentos, bloqueo_iniciado=False, ya_estaba_bloqueada=False)


def _reiniciar_intentos(usuario: Usuario) -> None:
    """Deja el contador en cero tras una contraseña correcta.

    No toca una cuenta que otra petición acaba de bloquear: la condición se
    evalúa en la misma sentencia UPDATE.
    """
    if usuario.intentos_fallidos or usuario.bloqueado_hasta:
        Usuario.objects.filter(_sin_bloqueo_vigente(timezone.now()), pk=usuario.pk).update(
            intentos_fallidos=0, bloqueado_hasta=None
        )


def iniciar_sesion(*, correo: str, password: str, peticion=None) -> ResultadoLogin:
    """Comprueba las credenciales y decide el paso siguiente.

    No emite tokens: eso lo hace la vista con el alcance que resulte. Un
    docente o administrador nunca sale de aquí con una sesión completa: o
    queda restringido a enrolar su 2FA, o debe verificar el segundo factor.

    No es una sola transacción a propósito: lo que deja un intento fallido
    (el contador y el bloqueo) se confirma antes de responder con el error.
    Si todo fuera una transacción, el error la desharía y el contador nunca
    avanzaría.
    """
    usuario = Usuario.objects.filter(correo=normalizar_correo(correo), is_active=True).first()
    if usuario is None:
        raise _credenciales_invalidas()

    if usuario.esta_bloqueado():
        # Mientras dure el bloqueo la contraseña se comprueba igual (cuesta lo
        # mismo que en los otros casos), pero no se cuenta ni deja entrar.
        if usuario.check_password(password):
            raise _cuenta_bloqueada()
        raise _credenciales_invalidas()

    if not usuario.check_password(password):
        contar_intento_fallido(usuario)
        raise _credenciales_invalidas()

    # Solo después de comprobar la contraseña: así este mensaje no le confirma
    # a un extraño que el correo existe.
    if usuario.rol == Rol.ALUMNO and not usuario.tiene_consentimiento:
        raise _sin_consentimiento()

    with transaction.atomic():
        _reiniciar_intentos(usuario)
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
