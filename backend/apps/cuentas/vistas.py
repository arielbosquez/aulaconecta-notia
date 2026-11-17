"""Endpoints de autenticación: ``/api/auth/`` (sección 11 de la arquitectura)."""

from django.conf import settings
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
from .limites import LimiteDeLoginPorIp
from .serializadores import SerializadorLogin
from .servicios import Paso, iniciar_sesion
from .tokens import alcance_vigente, emitir_tokens, usuario_del_token


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
        return respuesta


class VistaRefresh(APIView):
    """Cambia el token de refresco por un par nuevo. Cada refresco sirve una sola vez."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        exigir_csrf(request)
        tokens = self._rotar(request.COOKIES.get(settings.COOKIE_REFRESCO))
        if tokens is None:
            return self._sesion_terminada()
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        poner_cookies_de_sesion(respuesta, tokens)
        return respuesta

    @staticmethod
    @transaction.atomic
    def _rotar(crudo: str | None):
        """Devuelve tokens nuevos, o ``None`` si el refresco no vale."""
        if not crudo:
            return None
        try:
            # Comprueba firma, vencimiento, tipo y lista negra.
            refresco = RefreshToken(crudo)
        except TokenError:
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
