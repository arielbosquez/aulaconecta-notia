"""Cookies de sesión (RS-04).

Los dos tokens viajan en cookies ``HttpOnly`` (el JavaScript no las puede
leer), ``Secure`` (solo por HTTPS; los navegadores también las aceptan en
``http://localhost`` para desarrollar) y ``SameSite=Strict`` (no se envían en
peticiones que vienen de otro sitio). La de refresco, además, solo se envía a
las rutas de autenticación.
"""

from django.conf import settings
from rest_framework_simplejwt.settings import api_settings

from .tokens import TokensDeSesion

MISMO_SITIO = "Strict"
RUTA_ACCESO = "/"


def poner_cookies_de_sesion(respuesta, tokens: TokensDeSesion) -> None:
    """Agrega a la respuesta las cookies con los tokens de la sesión."""
    respuesta.set_cookie(
        settings.COOKIE_ACCESO,
        tokens.acceso,
        max_age=int(api_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
        path=RUTA_ACCESO,
        secure=True,
        httponly=True,
        samesite=MISMO_SITIO,
    )
    respuesta.set_cookie(
        settings.COOKIE_REFRESCO,
        tokens.refresco,
        max_age=int(api_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        path=settings.COOKIE_REFRESCO_RUTA,
        secure=True,
        httponly=True,
        samesite=MISMO_SITIO,
    )


def borrar_cookies_de_sesion(respuesta) -> None:
    """Pide al navegador que descarte las cookies de la sesión."""
    for nombre, ruta in (
        (settings.COOKIE_ACCESO, RUTA_ACCESO),
        (settings.COOKIE_REFRESCO, settings.COOKIE_REFRESCO_RUTA),
    ):
        # Se borra con los mismos atributos con que se creó; si no, el
        # navegador la trata como otra cookie y conserva la original.
        respuesta.set_cookie(
            nombre,
            "",
            max_age=0,
            path=ruta,
            secure=True,
            httponly=True,
            samesite=MISMO_SITIO,
        )
