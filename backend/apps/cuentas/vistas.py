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
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.csrf import exigir_csrf

from .cookies import borrar_cookies_de_sesion, poner_cookies_de_sesion
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
