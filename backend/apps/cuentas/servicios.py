"""Reglas del inicio de sesión (CU-01, sección 8.2) y del cambio de contraseña (CU-04)."""

import functools
import secrets
from dataclasses import dataclass
from enum import StrEnum

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError

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


MENSAJE_CREDENCIALES_INVALIDAS = (
    "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente. "
    "Intenta de nuevo en unos minutos."
)


def _credenciales_invalidas() -> ErrorApi:
    # El mismo error si el correo no existe, si la cuenta está desactivada, si
    # la contraseña no coincide o si la cuenta está bloqueada (con cualquier
    # contraseña, correcta o no): la respuesta no revela cuál fue el caso. Por
    # eso el mensaje nombra también el bloqueo.
    return ErrorApi(
        "credenciales_invalidas",
        MENSAJE_CREDENCIALES_INVALIDAS,
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


@functools.cache
def _hash_ficticio() -> str:
    """Hash Argon2id de una contraseña al azar que nadie conoce.

    Se calcula una vez por proceso, con los mismos parámetros que los hashes
    reales, para que comprobarlo cueste lo mismo.
    """
    return make_password(secrets.token_urlsafe(32))


def _gastar_lo_mismo_que_un_hash(password: str) -> None:
    """Ejecuta el hasher aunque no haya contra qué comparar.

    Sin esto, un correo inexistente respondería en pocos milisegundos y uno
    real tardaría lo que tarda Argon2id: la diferencia de tiempo revelaría
    qué correos existen (RS-03).
    """
    check_password(password, _hash_ficticio())


def _contrasena_correcta(usuario: Usuario, password: str) -> bool:
    """Compara la contraseña ejecutando siempre el hasher exactamente una vez."""
    if not usuario.has_usable_password():
        # Django responde al instante para una contraseña no utilizable.
        _gastar_lo_mismo_que_un_hash(password)
        return False
    return usuario.check_password(password)


def _sin_bloqueo_vigente(ahora) -> Q:
    return Q(bloqueado_hasta__isnull=True) | Q(bloqueado_hasta__lte=ahora)


def _registrar_fallo(motivo: str, *, usuario: Usuario | None, peticion, **detalle) -> None:
    """Deja un LOGIN_FALLIDO en la bitácora.

    El actor queda vacío: con la contraseña incorrecta no se sabe quién hizo
    el intento. La cuenta atacada, si existe, queda como el objeto. Nunca se
    guarda la contraseña escrita ni el correo de un intento con un correo
    inexistente (a veces la persona escribe su contraseña en el campo del
    correo).
    """
    registrar(
        Accion.LOGIN_FALLIDO,
        peticion=peticion,
        objeto=usuario,
        detalle={"motivo": motivo, **detalle},
    )


@transaction.atomic
def contar_intento_fallido(
    usuario: Usuario, *, peticion=None, motivo: str = "credenciales"
) -> IntentoFallido:
    """Suma una contraseña incorrecta a la cuenta y la bloquea al llegar al límite.

    Cuentan tanto los fallos del login como los de la contraseña actual al
    cambiarla: ``motivo`` distingue unos de otros en la bitácora.

    Es a prueba de peticiones simultáneas: la fila del usuario se bloquea
    (``SELECT … FOR UPDATE``) y el contador se lee de la base, no del objeto
    que la petición cargó antes de comprobar la contraseña. Así, si llegan
    varias contraseñas incorrectas a la vez, cada una suma la suya y solo una
    de ellas bloquea la cuenta.

    Al bloquear, el contador vuelve a cero: cuando el bloqueo vence, la cuenta
    tiene de nuevo 5 intentos.

    El contador, el bloqueo y sus registros en la bitácora se confirman en la
    misma transacción: no puede quedar uno sin el otro.
    """
    fila = Usuario.objects.select_for_update().values("intentos_fallidos", "bloqueado_hasta")
    actual = fila.get(pk=usuario.pk)
    ahora = timezone.now()

    if actual["bloqueado_hasta"] is not None and actual["bloqueado_hasta"] > ahora:
        # Otra petición la bloqueó mientras esta calculaba el hash. El
        # bloqueo ya corre: este intento no lo alarga ni suma.
        _registrar_fallo("cuenta_bloqueada", usuario=usuario, peticion=peticion)
        return IntentoFallido(
            intentos=actual["intentos_fallidos"], bloqueo_iniciado=False, ya_estaba_bloqueada=True
        )

    intentos = actual["intentos_fallidos"] + 1
    _registrar_fallo(motivo, usuario=usuario, peticion=peticion, intentos_fallidos=intentos)
    if intentos >= settings.LOGIN_INTENTOS_ANTES_DE_BLOQUEAR:
        hasta = ahora + settings.LOGIN_DURACION_DEL_BLOQUEO
        Usuario.objects.filter(pk=usuario.pk).update(intentos_fallidos=0, bloqueado_hasta=hasta)
        # Lo hace el sistema, no una persona: sin actor.
        registrar(
            Accion.CUENTA_BLOQUEADA,
            peticion=peticion,
            objeto=usuario,
            detalle={"intentos_fallidos": intentos, "bloqueado_hasta": hasta.isoformat()},
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

    Sin enumeración de usuarios (RS-03): en todos los caminos se ejecuta el
    hasher una sola vez, y el correo inexistente, la cuenta desactivada, la
    contraseña incorrecta y la cuenta bloqueada responden el mismo error.
    """
    # El hash ficticio se prepara antes de buscar al usuario: así el costo de
    # crearlo (solo la primera vez en cada proceso) lo pagan todos por igual.
    _hash_ficticio()
    usuario = Usuario.objects.filter(correo=normalizar_correo(correo), is_active=True).first()
    if usuario is None:
        # Correo inexistente o cuenta desactivada: mismo costo, mismo error.
        _gastar_lo_mismo_que_un_hash(password)
        _registrar_fallo("credenciales", usuario=None, peticion=peticion)
        raise _credenciales_invalidas()

    if usuario.esta_bloqueado():
        # Mientras dure el bloqueo la contraseña NO se compara con la real: si
        # una contraseña correcta recibiera otra respuesta (antes, un 423), el
        # bloqueo serviría de oráculo y se podría seguir adivinando durante
        # los 15 minutos. Se ejecuta el hasher contra el hash ficticio, que
        # cuesta lo mismo, y la respuesta es el mismo error genérico.
        _gastar_lo_mismo_que_un_hash(password)
        _registrar_fallo("cuenta_bloqueada", usuario=usuario, peticion=peticion)
        raise _credenciales_invalidas()

    if not _contrasena_correcta(usuario, password):
        contar_intento_fallido(usuario, peticion=peticion)
        raise _credenciales_invalidas()

    # Solo después de comprobar la contraseña: así este mensaje no le confirma
    # a un extraño que el correo existe.
    if usuario.rol == Rol.ALUMNO and not usuario.tiene_consentimiento:
        # La contraseña era correcta: aquí sí se sabe quién intentó entrar.
        registrar(
            Accion.LOGIN_FALLIDO,
            actor=usuario,
            peticion=peticion,
            detalle={"motivo": "sin_consentimiento"},
        )
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


# --- Cambio de contraseña (CU-04) ----------------------------------------------

MENSAJE_CONTRASENA_ACTUAL_INCORRECTA = (
    "La contraseña actual no es correcta, o la cuenta está bloqueada temporalmente. "
    "Intenta de nuevo en unos minutos."
)


def _password_actual_incorrecta() -> ErrorApi:
    # 400 y no 401: la sesión sí es válida, y un 401 haría que el navegador
    # intentara renovarla. Durante el bloqueo responde lo mismo (sin oráculo).
    return ErrorApi(
        "password_actual_incorrecta",
        MENSAJE_CONTRASENA_ACTUAL_INCORRECTA,
        estado=status.HTTP_400_BAD_REQUEST,
    )


def _validar_password_nueva(usuario: Usuario, actual: str, nueva: str) -> None:
    """Aplica la política de contraseñas (RS-01) a la contraseña nueva."""
    errores = []
    if nueva == actual:
        errores.append("La contraseña nueva debe ser distinta de la actual.")
    try:
        validate_password(nueva, user=usuario)
    except DjangoValidationError as error:
        errores.extend(error.messages)
    if errores:
        raise ValidationError({"password_nueva": errores})


def cambiar_password(usuario: Usuario, *, actual: str, nueva: str, peticion=None) -> Usuario:
    """Cambia la contraseña de quien tiene la sesión abierta.

    Exige la contraseña actual aunque la sesión sea válida: quien encuentre
    un computador con la sesión abierta no puede cambiarla y quedarse con la
    cuenta. Cada contraseña actual incorrecta suma al bloqueo igual que en el
    login, así la sesión tampoco sirve para adivinarla. Durante el bloqueo no
    se compara con la real.

    Es la salida de la contraseña temporal: deja ``debe_cambiar_password`` en
    ``False``. Devuelve el usuario actualizado.
    """
    _hash_ficticio()
    if usuario.esta_bloqueado():
        _gastar_lo_mismo_que_un_hash(actual)
        _registrar_fallo("cuenta_bloqueada", usuario=usuario, peticion=peticion)
        raise _password_actual_incorrecta()

    if not _contrasena_correcta(usuario, actual):
        contar_intento_fallido(usuario, peticion=peticion, motivo="password_actual_incorrecta")
        raise _password_actual_incorrecta()

    _validar_password_nueva(usuario, actual, nueva)

    with transaction.atomic():
        cuenta = Usuario.objects.select_for_update().get(pk=usuario.pk)
        cuenta.set_password(nueva)
        cuenta.debe_cambiar_password = False
        cuenta.intentos_fallidos = 0
        cuenta.save(update_fields=["password", "debe_cambiar_password", "intentos_fallidos"])
        registrar(Accion.PASSWORD_CAMBIADA, actor=cuenta, peticion=peticion)
    return cuenta
