"""Configuración de desarrollo local. No se usa nunca en un servidor."""

from apps.core.llaves import nueva_llave_fernet, nueva_llave_secreta

from .base import *  # noqa: F403
from .base import ALLOWED_HOSTS, JWT_SIGNING_KEY, MFA_ENCRYPTION_KEY, SECRET_KEY

DEBUG = True

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Si falta una llave en backend/.env se genera una al arrancar, válida solo
# mientras dure el proceso. Así no queda ninguna llave escrita en el código.
# Para que las sesiones y el 2FA sobrevivan a un reinicio, guarda en
# backend/.env las que entrega: python manage.py generar_llaves
if not SECRET_KEY:
    SECRET_KEY = nueva_llave_secreta()
if not JWT_SIGNING_KEY:
    JWT_SIGNING_KEY = nueva_llave_secreta()
if not MFA_ENCRYPTION_KEY:
    MFA_ENCRYPTION_KEY = nueva_llave_fernet()
