"""Configuración para las pruebas automáticas (pytest)."""

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F403

DEBUG = False

ALLOWED_HOSTS = ["testserver", "localhost"]

# Llave distinta en cada ejecución: las pruebas no dependen de un valor fijo.
SECRET_KEY = get_random_secret_key()
