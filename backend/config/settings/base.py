"""Configuración común a todos los entornos.

Aquí solo hay valores no sensibles. Las llaves y contraseñas llegan por
variables de entorno, leídas con ``config.entorno``: si falta una variable
obligatoria en producción, el arranque se detiene.
"""

from datetime import timedelta
from pathlib import Path

from config.entorno import (
    cargar_archivo_env,
    es_produccion,
    leer,
    leer_entero,
    leer_lista,
    leer_opcion,
)
from config.sesion import RUTA_COOKIE_REFRESCO, nombres_de_cookies

# Carpeta backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# backend/.env es solo para el computador de cada integrante (está en
# .gitignore). En producción las variables las entrega App Service.
if not es_produccion():
    cargar_archivo_env(BASE_DIR / ".env")

# Tres llaves distintas entre sí. Base nunca trae una escrita: en desarrollo
# y pruebas, si faltan, cada entorno genera una temporal.
SECRET_KEY = leer("DJANGO_SECRET_KEY", obligatoria=True)
JWT_SIGNING_KEY = leer("JWT_SIGNING_KEY", obligatoria=True)
MFA_ENCRYPTION_KEY = leer("MFA_ENCRYPTION_KEY", obligatoria=True)

DEBUG = False

ALLOWED_HOSTS = leer_lista("ALLOWED_HOSTS", obligatoria=True)
CSRF_TRUSTED_ORIGINS = leer_lista("CSRF_TRUSTED_ORIGINS")

# Django solo expone la API REST: no se instalan el admin, las sesiones,
# los mensajes ni los archivos estáticos de Django.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
    # Lista negra de tokens de refresco ya rotados o cerrados.
    "rest_framework_simplejwt.token_blacklist",
    "apps.core",
    "apps.cuentas",
    "apps.academico",
    "apps.evaluaciones",
    "apps.voz",
    "apps.rendicion",
    "apps.resultados",
    "apps.integridad",
    "apps.auditoria",
]

# Modelo de usuario propio, definido antes de la primera migración.
AUTH_USER_MODEL = "cuentas.Usuario"

MIDDLEWARE = [
    # Primero, para que las cabeceras de seguridad cubran todas las respuestas.
    "apps.core.middleware.CabecerasSeguridadMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Sin templates de Django: todas las pantallas son de Astro.
TEMPLATES: list[dict] = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": leer("DB_HOST", defecto="127.0.0.1", obligatoria=True),
        "PORT": leer("DB_PORT", defecto="5432"),
        "NAME": leer("DB_NAME", defecto="notia", obligatoria=True),
        # La aplicación se conecta con el rol de privilegios mínimos.
        "USER": leer("DB_USER", defecto="notia_app", obligatoria=True),
        "PASSWORD": leer("DB_PASSWORD", obligatoria=True),
        "OPTIONS": {
            # Si la base no responde, la petición falla pronto en vez de quedar colgada.
            "connect_timeout": 5,
            "sslmode": leer_opcion(
                "DB_SSLMODE",
                opciones=("disable", "allow", "prefer", "require", "verify-ca", "verify-full"),
                defecto="prefer",
            ),
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Contraseñas solo con Argon2id (RS-01). No hay otro algoritmo en la lista:
# una contraseña guardada con un hash más débil no se aceptaría.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]

# Largo mínimo por rol. Las variables de entorno permiten exigir más, nunca menos.
PASSWORD_LARGO_MINIMO_ALUMNO = leer_entero("PASSWORD_LARGO_MINIMO_ALUMNO", defecto=10, minimo=10)
PASSWORD_LARGO_MINIMO_PERSONAL = leer_entero(
    "PASSWORD_LARGO_MINIMO_PERSONAL", defecto=12, minimo=12
)

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("correo", "nombres", "apellidos")},
    },
    {"NAME": "apps.cuentas.validadores.LargoMinimoPorRol"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Hashes SHA-256 de los scripts y estilos en línea del build de Astro. Los
# genera frontend/scripts/hash-csp.mjs y el middleware los lee al arrancar.
CSP_ARCHIVO_HASHES = BASE_DIR.parent / "frontend" / "csp-hashes.json"

# --- Sesiones: JWT en cookies (sección 8.1) ---
# Token de acceso corto y token de refresco de una jornada escolar. Al
# renovar, el refresco se cambia por uno nuevo y el anterior queda en la
# lista negra. Se firman con una llave propia, distinta de SECRET_KEY.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=8),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "sub",
    "UPDATE_LAST_LOGIN": False,
}

# Los tokens viajan solo en cookies HttpOnly, Secure y SameSite=Strict: el
# JavaScript nunca los ve. Los nombres llevan prefijo en producción.
_COOKIES = nombres_de_cookies(produccion=es_produccion())
COOKIE_ACCESO = _COOKIES["acceso"]
COOKIE_REFRESCO = _COOKIES["refresco"]
COOKIE_REFRESCO_RUTA = RUTA_COOKIE_REFRESCO

# El token CSRF sí lo lee el JavaScript (para enviarlo en X-CSRFToken), pero
# tampoco viaja a otros sitios.
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_HTTPONLY = False

# La API responde solo JSON y niega el acceso por omisión: cada vista debe
# declarar sus permisos.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Sesión por cookie, con CSRF exigido en los métodos que modifican datos.
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.cuentas.autenticacion.AutenticacionPorCookie"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    # Errores con la forma {"codigo", "mensaje"}, en español y sin trazas.
    "EXCEPTION_HANDLER": "apps.core.errores.manejador_de_excepciones",
}

# El rechazo por CSRF también responde JSON genérico.
CSRF_FAILURE_VIEW = "apps.core.errores.error_csrf"

# Registros en JSON por la salida estándar (los recoge App Service). Todo pasa
# por el filtro que enmascara contraseñas, tokens, cookies y respuestas.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "datos_sensibles": {"()": "apps.core.registros.FiltroDatosSensibles"},
    },
    "formatters": {
        "json": {"()": "apps.core.registros.FormateadorJson"},
    },
    "handlers": {
        "consola": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
            "filters": ["datos_sensibles"],
        },
    },
    "root": {"handlers": ["consola"], "level": "INFO"},
    "loggers": {
        # Los registros de Django usan el mismo formato y el mismo filtro.
        "django": {"handlers": [], "level": "INFO", "propagate": True},
        "django.server": {"handlers": [], "level": "INFO", "propagate": True},
        # Nunca se registran las consultas SQL: llevan datos de las personas.
        "django.db.backends": {"level": "WARNING"},
    },
}

# --- Cuentas ---
DOMINIO_INSTITUCIONAL = leer("DOMINIO_INSTITUCIONAL", defecto="aulaconecta.cl").lower()

# --- Voz ---
# "prueba" genera audios sintéticos sin red; "azure" usa Azure AI Speech.
PROVEEDOR_VOZ = leer_opcion("PROVEEDOR_VOZ", opciones=("azure", "prueba"), defecto="prueba")
AZURE_SPEECH_KEY = leer("AZURE_SPEECH_KEY", obligatoria=PROVEEDOR_VOZ == "azure")
AZURE_SPEECH_REGION = leer("AZURE_SPEECH_REGION", obligatoria=PROVEEDOR_VOZ == "azure")
VOCES_DISPONIBLES = leer_lista(
    "VOCES_DISPONIBLES", defecto=("es-CL-CatalinaNeural", "es-CL-LorenzoNeural")
)

# --- Almacenamiento privado (Blob Storage con identidad administrada) ---
AZURE_STORAGE_ACCOUNT_NAME = leer("AZURE_STORAGE_ACCOUNT_NAME", obligatoria=True)
AZURE_STORAGE_CONTAINER = leer("AZURE_STORAGE_CONTAINER", obligatoria=True)
