"""Autenticación de la API con el token de acceso de la cookie (RS-04 y RS-05)."""

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.csrf import exigir_csrf

from .tokens import usuario_del_token


class AutenticacionPorCookie(BaseAuthentication):
    """Identifica al usuario por la cookie de acceso.

    El token nunca se acepta desde la cabecera ``Authorization`` ni desde el
    cuerpo: solo desde la cookie ``HttpOnly``, que el JavaScript no puede leer.

    Como el navegador envía las cookies por su cuenta, toda petición
    autenticada que modifique datos debe traer además el token CSRF.
    """

    # Con esto, una petición sin sesión responde 401 y no 403.
    ESQUEMA = "Cookie"

    def authenticate(self, request):
        crudo = request.COOKIES.get(settings.COOKIE_ACCESO)
        if not crudo:
            return None

        try:
            # Comprueba la firma, el vencimiento y que sea un token de acceso.
            token = AccessToken(crudo)
        except TokenError as error:
            raise AuthenticationFailed() from error

        usuario = usuario_del_token(token)
        if usuario is None:
            raise AuthenticationFailed()

        exigir_csrf(request)
        return usuario, token

    def authenticate_header(self, request):
        return self.ESQUEMA
