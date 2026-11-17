"""Configuración para las pruebas automáticas (pytest)."""

from apps.core.llaves import nueva_llave_fernet, nueva_llave_secreta

from .base import *  # noqa: F403

DEBUG = False

ALLOWED_HOSTS = ["testserver", "localhost"]

# Llaves distintas en cada ejecución: las pruebas no dependen de un valor
# fijo ni de las llaves que el integrante tenga en su backend/.env.
SECRET_KEY = nueva_llave_secreta()
JWT_SIGNING_KEY = nueva_llave_secreta()
MFA_ENCRYPTION_KEY = nueva_llave_fernet()
