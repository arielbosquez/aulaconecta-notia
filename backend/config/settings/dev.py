"""Configuración de desarrollo local. No se usa nunca en un servidor."""

from apps.core.llaves import nueva_llave_fernet, nueva_llave_secreta
from config.entorno import leer, leer_opcion

from .base import *  # noqa: F403
from .base import ALLOWED_HOSTS, DATABASES, JWT_SIGNING_KEY, MFA_ENCRYPTION_KEY, SECRET_KEY

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

# La aplicación se conecta siempre como notia_app, que no puede crear tablas.
# Las migraciones se ejecutan como notia_owner, pidiéndolo de forma explícita:
#   $env:DB_ROL = 'owner'; python manage.py migrate; Remove-Item Env:DB_ROL
if leer_opcion("DB_ROL", opciones=("app", "owner"), defecto="app") == "owner":
    DATABASES["default"]["USER"] = "notia_owner"
    DATABASES["default"]["PASSWORD"] = leer("DB_OWNER_PASSWORD")
