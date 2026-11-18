"""Configuración para las pruebas automáticas (pytest)."""

from apps.core.llaves import nueva_llave_fernet, nueva_llave_secreta

from .base import *  # noqa: F403
from .base import SIMPLE_JWT

DEBUG = False

ALLOWED_HOSTS = ["testserver", "localhost"]

# Llaves distintas en cada ejecución: las pruebas no dependen de un valor
# fijo ni de las llaves que el integrante tenga en su backend/.env.
SECRET_KEY = nueva_llave_secreta()
JWT_SIGNING_KEY = nueva_llave_secreta()
MFA_ENCRYPTION_KEY = nueva_llave_fernet()
SIMPLE_JWT["SIGNING_KEY"] = JWT_SIGNING_KEY

# El servidor de las pruebas en el navegador (live_server) revisa STATIC_URL
# para decidir qué rutas son archivos estáticos de Django. El proyecto no usa
# django.contrib.staticfiles (las pantallas las sirve WhiteNoise desde
# WHITENOISE_ROOT), así que basta con un prefijo que nadie usa.
STATIC_URL = "/_estaticos_de_pruebas/"
