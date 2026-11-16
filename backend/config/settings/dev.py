"""Configuración de desarrollo local. No se usa nunca en un servidor."""

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F403
from .base import SECRET_KEY

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Si no hay llave en el entorno se genera una al arrancar, válida solo
# mientras dure el proceso. Así no queda ninguna llave escrita en el código.
if not SECRET_KEY:
    SECRET_KEY = get_random_secret_key()
