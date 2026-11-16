"""Configuración común a todos los entornos.

Aquí solo hay valores no sensibles. Las llaves y contraseñas llegan por
variables de entorno, leídas con ``config.entorno``: si falta una variable
obligatoria en producción, el arranque se detiene.
"""

from pathlib import Path

from config.entorno import cargar_archivo_env, es_produccion, leer, leer_lista, leer_opcion

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
        "HOST": leer("DB_HOST", defecto="localhost", obligatoria=True),
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

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

X_FRAME_OPTIONS = "DENY"

# La API responde solo JSON y niega el acceso por omisión: cada vista debe
# declarar sus permisos. La autenticación por cookies se agrega en la Fase 1.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
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
