"""Configuración de producción (Azure App Service).

Las variables obligatorias se leen con ``os.environ[...]`` para que el
arranque falle de inmediato si falta alguna, en vez de seguir con un valor
inseguro.
"""

import os

from .base import *  # noqa: F403
from .base import DATABASES

DEBUG = False

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

ALLOWED_HOSTS = [host.strip() for host in os.environ["ALLOWED_HOSTS"].split(",") if host.strip()]

CSRF_TRUSTED_ORIGINS = [
    origen.strip()
    for origen in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origen.strip()
]

# La base de datos de producción exige contraseña y conexión cifrada.
DATABASES["default"]["PASSWORD"] = os.environ["DB_PASSWORD"]
DATABASES["default"]["OPTIONS"]["sslmode"] = "require"

# HTTPS obligatorio. App Service termina TLS y avisa con esta cabecera.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
