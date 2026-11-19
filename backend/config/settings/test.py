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

# Las pruebas nunca llaman a Azure, aunque el backend/.env del integrante diga
# PROVEEDOR_VOZ=azure: siempre usan el proveedor sin red, y la llave de Azure
# ni siquiera queda en la configuración del proceso de pruebas.
PROVEEDOR_VOZ = "prueba"
AZURE_SPEECH_KEY = ""
AZURE_SPEECH_REGION = ""

# El servidor de las pruebas en el navegador (live_server) revisa STATIC_URL
# para decidir qué rutas son archivos estáticos de Django. El proyecto no usa
# django.contrib.staticfiles (las pantallas las sirve WhiteNoise desde
# WHITENOISE_ROOT), así que basta con un prefijo que nadie usa.
STATIC_URL = "/_estaticos_de_pruebas/"

# Audios e imágenes en memoria: las pruebas no dejan archivos en el disco.
_EN_MEMORIA = {"BACKEND": "apps.core.almacenamiento.AlmacenamientoEnMemoria"}
STORAGES = {"default": _EN_MEMORIA, "privado": _EN_MEMORIA}
