"""Endpoints de autenticación: ``/api/auth/`` (sección 11 de la arquitectura)."""

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.middleware.csrf import get_token, rotate_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar
from apps.core.csrf import exigir_csrf

from .cookies import borrar_cookies_de_sesion, poner_cookies_de_sesion
from .limites import LimiteDeLoginPorIp, LimiteDeVerificacionMfa
from .mfa import (
    confirmar_enrolamiento,
    emitir_ticket,
    iniciar_enrolamiento,
    leer_ticket,
    ticket_invalido,
    verificar_segundo_factor,
)
from .models import Usuario
from .serializadores import (
    SerializadorCambioPassword,
    SerializadorCodigoMfa,
    SerializadorLogin,
)
from .servicios import Paso, cambiar_password, iniciar_sesion
from .tokens import (
    Alcance,
    alcance_vigente,
    datos_de_refresco_reutilizado,
    emitir_tokens,
    usuario_del_token,
)

# Un mismo refresco reutilizado deja como máximo un registro por minuto.
SEGUNDOS_ENTRE_AVISOS_DE_REUTILIZACION = 60


class VistaCsrf(APIView):
    """Entrega la cookie ``csrftoken`` que el navegador debe devolver en ``X-CSRFToken``."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        get_token(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class VistaLogin(APIView):
    """CU-01: inicia sesión con correo y contraseña."""

    # Sin autenticación previa: una cookie vieja o inválida no impide entrar.
    authentication_classes = []
    permission_classes = [AllowAny]
    # Se aplica antes que todo lo demás (CSRF, validación y contraseña):
    # pasado el límite, la petición responde 429 sin calcular ningún hash.
    throttle_classes = [LimiteDeLoginPorIp]

    def post(self, request):
        exigir_csrf(request)
        datos = SerializadorLogin(data=request.data)
        datos.is_valid(raise_exception=True)

        resultado = iniciar_sesion(
            correo=datos.validated_data["correo"],
            password=datos.validated_data["password"],
            peticion=request,
        )

        cuerpo = {"paso": resultado.paso.value}
        respuesta = Response(cuerpo)
        if resultado.paso is Paso.LISTO:
            cuerpo["debe_cambiar_password"] = resultado.usuario.debe_cambiar_password
        if resultado.alcance is not None:
            # Sesión completa para un alumno; restringida a enrolar el 2FA
            # para un docente o administrador que aún no lo activa.
            tokens = emitir_tokens(resultado.usuario, resultado.alcance)
            poner_cookies_de_sesion(respuesta, tokens)
            # Token CSRF nuevo para la sesión que empieza.
            rotate_token(request._request)
        elif resultado.paso is Paso.MFA:
            # Personal con 2FA: ninguna sesión todavía, solo el ticket firmado
            # para enviar el código (5 minutos, cookie HttpOnly).
            poner_cookie_de_ticket(respuesta, emitir_ticket(resultado.usuario))
        return respuesta


def _registrar_si_es_reutilizado(crudo: str, peticion) -> None:
    """Deja en la bitácora el uso de un refresco que ya se había usado (RA-02).

    Un refresco repetido puede ser un robo o solo dos pestañas que renovaron
    a la vez. No se cierran las demás sesiones (ver RA-02), pero queda
    constancia para que el administrador pueda revisarlo (CU-16).

    - Nunca se guarda el token: solo la cuenta a la que pertenece, la IP, el
      navegador y el motivo.
    - Sin actor: quien lo usó pudo no ser el dueño de la cuenta.
    - Como pide la sección 10 para los accesos denegados, con límite de
      frecuencia: un registro por token cada minuto, aunque se repita mil
      veces. La marca vive en la caché, con el identificador del token (jti),
      que no sirve para nada sin el token firmado.
    """
    datos = datos_de_refresco_reutilizado(crudo)
    if datos is None:
        return
    marca = f"refresco_reutilizado:{datos[api_settings.JTI_CLAIM]}"
    if not cache.add(marca, True, timeout=SEGUNDOS_ENTRE_AVISOS_DE_REUTILIZACION):
        return
    cuenta = Usuario.objects.filter(pk=datos.get(api_settings.USER_ID_CLAIM)).first()
    registrar(
        Accion.ACCESO_DENEGADO,
        peticion=peticion,
        objeto=cuenta,
        detalle={"motivo": "refresco_reutilizado"},
    )


class VistaRefresh(APIView):
    """Cambia el token de refresco por un par nuevo. Cada refresco sirve una sola vez."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        exigir_csrf(request)
        tokens = self._rotar(request.COOKIES.get(settings.COOKIE_REFRESCO), request)
        if tokens is None:
            return self._sesion_terminada()
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        poner_cookies_de_sesion(respuesta, tokens)
        return respuesta

    @staticmethod
    @transaction.atomic
    def _rotar(crudo: str | None, peticion):
        """Devuelve tokens nuevos, o ``None`` si el refresco no vale."""
        if not crudo:
            return None
        try:
            # Comprueba firma, vencimiento, tipo y lista negra.
            refresco = RefreshToken(crudo)
        except TokenError:
            _registrar_si_es_reutilizado(crudo, peticion)
            return None

        # Se bloquea el registro del token: dos peticiones simultáneas con el
        # mismo refresco no pueden obtener cada una su par nuevo.
        emitido = (
            OutstandingToken.objects.select_for_update()
            .filter(jti=refresco[api_settings.JTI_CLAIM])
            .first()
        )
        if emitido is None:
            return None
        try:
            refresco.check_blacklist()
        except TokenError:
            # Otra petición lo usó mientras esta esperaba el bloqueo.
            _registrar_si_es_reutilizado(crudo, peticion)
            return None

        usuario = usuario_del_token(refresco)
        if usuario is None:
            return None
        # El par nuevo conserva el alcance: renovar nunca amplía una sesión.
        alcance = alcance_vigente(usuario, refresco)
        if alcance is None:
            return None

        refresco.blacklist()
        return emitir_tokens(usuario, alcance)

    @staticmethod
    def _sesion_terminada() -> Response:
        respuesta = Response(
            {"codigo": "sesion_expirada", "mensaje": "Tu sesión terminó. Vuelve a iniciar sesión."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
        borrar_cookies_de_sesion(respuesta)
        return respuesta


class VistaLogout(APIView):
    """CU-03: cierra la sesión de este navegador.

    Pone el token de refresco en la lista negra y borra las dos cookies. Las
    demás sesiones del usuario siguen abiertas: para cerrarlas todas está el
    cambio de contraseña (o, en la Fase 4, el administrador).

    No exige un token de acceso vigente: dura solo 5 minutos y cerrar sesión
    debe funcionar igual con uno vencido. Basta con la cookie de refresco, o
    con ninguna (entonces solo se borran las cookies). Sí exige CSRF, para
    que otro sitio no pueda cerrar la sesión de nadie.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        exigir_csrf(request)
        usuario = self._anular_refresco(request.COOKIES.get(settings.COOKIE_REFRESCO))
        if usuario is None:
            usuario = self._usuario_del_acceso(request.COOKIES.get(settings.COOKIE_ACCESO))
        if usuario is not None:
            registrar(Accion.LOGOUT, actor=usuario, peticion=request)

        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        borrar_cookies_de_sesion(respuesta)
        # El token CSRF de la sesión que termina no se reutiliza.
        rotate_token(request._request)
        return respuesta

    @staticmethod
    @transaction.atomic
    def _anular_refresco(crudo: str | None):
        """Pone el refresco en la lista negra y devuelve a su dueño, o ``None``."""
        if not crudo:
            return None
        try:
            refresco = RefreshToken(crudo)
        except TokenError:
            # Vencido, falso o ya anulado: no hay nada que cerrar.
            return None
        # Mismo bloqueo que la renovación: un logout y un refresh simultáneos
        # con el mismo token se ordenan y no chocan al escribir la lista negra.
        # Si el refresh llega primero, su par nuevo queda vivo en ese
        # navegador; cerrar todas las sesiones es tarea del cambio de
        # contraseña.
        emitido = (
            OutstandingToken.objects.select_for_update()
            .filter(jti=refresco[api_settings.JTI_CLAIM])
            .first()
        )
        if emitido is None or BlacklistedToken.objects.filter(token=emitido).exists():
            return None
        BlacklistedToken.objects.create(token=emitido)
        return usuario_del_token(refresco)

    @staticmethod
    def _usuario_del_acceso(crudo: str | None):
        if not crudo:
            return None
        try:
            return usuario_del_token(AccessToken(crudo))
        except TokenError:
            return None


class VistaCambiarPassword(APIView):
    """CU-04: cambia la contraseña de la sesión actual.

    Es uno de los dos endpoints (con el logout) que puede usar una cuenta
    con la contraseña temporal pendiente de cambio: el resto de la API la
    rechaza con ``SesionCompleta`` hasta que la cambie. También lo puede usar
    una sesión restringida a enrolar el 2FA, para que el personal con
    contraseña temporal no quede trabado.

    Al cambiarla se cierran todas las sesiones de la cuenta (sección 8.1).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        datos = SerializadorCambioPassword(data=request.data)
        datos.is_valid(raise_exception=True)
        cuenta = cambiar_password(
            request.user,
            actual=datos.validated_data["password_actual"],
            nueva=datos.validated_data["password_nueva"],
            peticion=request,
        )
        # El cambio cerró todas las sesiones, también esta. Quien acaba de
        # demostrar que conoce la contraseña recibe un par nuevo con la
        # versión nueva y el mismo alcance: cambiar la contraseña nunca
        # convierte una sesión restringida en completa.
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        poner_cookies_de_sesion(respuesta, emitir_tokens(cuenta, request.alcance))
        rotate_token(request._request)
        return respuesta


def poner_cookie_de_ticket(respuesta, ticket: str) -> None:
    respuesta.set_cookie(
        settings.COOKIE_TICKET_MFA,
        ticket,
        max_age=int(settings.MFA_DURACION_DEL_TICKET.total_seconds()),
        path=settings.COOKIE_TICKET_MFA_RUTA,
        secure=True,
        httponly=True,
        samesite="Strict",
    )


def borrar_cookie_de_ticket(respuesta) -> None:
    respuesta.set_cookie(
        settings.COOKIE_TICKET_MFA,
        "",
        max_age=0,
        path=settings.COOKIE_TICKET_MFA_RUTA,
        secure=True,
        httponly=True,
        samesite="Strict",
    )


class VistaVerificarMfa(APIView):
    """CU-02: segundo paso del login del personal, con el ticket del primero.

    Recibe el código del TOTP o un código de recuperación. Si sirve, entrega
    la sesión completa y gasta el ticket.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LimiteDeVerificacionMfa]

    def post(self, request):
        exigir_csrf(request)
        ticket = leer_ticket(request.COOKIES.get(settings.COOKIE_TICKET_MFA))
        if ticket is None:
            respuesta = Response(
                {"codigo": "ticket_invalido", "mensaje": ticket_invalido().mensaje},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            borrar_cookie_de_ticket(respuesta)
            return respuesta

        datos = SerializadorCodigoMfa(data=request.data)
        datos.is_valid(raise_exception=True)
        resultado = verificar_segundo_factor(
            ticket, datos.validated_data["codigo"], peticion=request
        )

        cuerpo = {
            "paso": Paso.LISTO.value,
            "debe_cambiar_password": resultado.usuario.debe_cambiar_password,
        }
        if resultado.codigos_restantes is not None:
            # Avisa cuántos códigos de recuperación le quedan.
            cuerpo["codigos_restantes"] = resultado.codigos_restantes
        respuesta = Response(cuerpo)
        poner_cookies_de_sesion(respuesta, emitir_tokens(resultado.usuario, Alcance.COMPLETA))
        borrar_cookie_de_ticket(respuesta)
        rotate_token(request._request)
        return respuesta


class VistaEnrolarMfa(APIView):
    """Inicia la activación del 2FA: entrega el QR y el secreto (RS-06).

    La usa la sesión restringida a enrolar el 2FA: el personal no obtiene una
    sesión completa sin él. Exige haber cambiado antes la contraseña temporal.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response(iniciar_enrolamiento(request.user))


class VistaConfirmarMfa(APIView):
    """Termina la activación del 2FA con un código de la aplicación (RS-06).

    Si el código sirve, se cierran todas las sesiones de la cuenta y este
    navegador recibe una sesión completa: la persona ya demostró la
    contraseña y el segundo factor.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        datos = SerializadorCodigoMfa(data=request.data)
        datos.is_valid(raise_exception=True)
        cuenta = confirmar_enrolamiento(
            request.user, datos.validated_data["codigo"], peticion=request
        )
        # Los códigos de recuperación se muestran esta única vez.
        respuesta = Response(
            {
                "paso": Paso.LISTO.value,
                "debe_cambiar_password": False,
                "codigos_recuperacion": cuenta.codigos_nuevos,
            }
        )
        poner_cookies_de_sesion(respuesta, emitir_tokens(cuenta, Alcance.COMPLETA))
        rotate_token(request._request)
        return respuesta


class VistaYo(APIView):
    """Datos mínimos de la sesión actual: nombre, rol y pendientes."""

    # También responde a una sesión restringida: es como el navegador se
    # entera de qué paso le falta.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        usuario = request.user
        return Response(
            {
                "nombre": usuario.nombre_completo,
                "rol": usuario.rol,
                "pendientes": {
                    "cambiar_password": usuario.debe_cambiar_password,
                    "enrolar_mfa": usuario.es_del_personal and not usuario.mfa_habilitado,
                },
            }
        )
