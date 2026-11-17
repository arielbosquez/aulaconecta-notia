"""Configuración de producción (Azure App Service).

Las variables obligatorias ya se exigieron en ``base`` (``config.entorno``
detiene el arranque si falta alguna). Aquí se agregan las comprobaciones y
los ajustes que solo valen en producción.
"""

from apps.core.llaves import validar_llaves
from config.entorno import leer_opcion

from .base import *  # noqa: F403
from .base import DATABASES, JWT_SIGNING_KEY, MFA_ENCRYPTION_KEY, SECRET_KEY

DEBUG = False

# Llaves largas, con el formato correcto y distintas entre sí.
validar_llaves(secreta=SECRET_KEY, jwt=JWT_SIGNING_KEY, mfa=MFA_ENCRYPTION_KEY)

# La conexión a la base de datos siempre va cifrada: no se acepta un modo
# que permita caer a texto plano.
DATABASES["default"]["OPTIONS"]["sslmode"] = leer_opcion(
    "DB_SSLMODE", opciones=("require", "verify-ca", "verify-full"), defecto="require"
)

# HTTPS obligatorio. App Service termina TLS y avisa con esta cabecera.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
