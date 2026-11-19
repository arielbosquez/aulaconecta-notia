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
from config.sesion import (
    RUTA_COOKIE_REFRESCO,
    RUTA_COOKIE_TICKET_MFA,
    nombre_cookie_ticket_mfa,
    nombres_de_cookies,
)

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

# Cuántos proxies propios hay delante de Django. De eso depende qué entrada
# de X-Forwarded-For es la IP real del cliente (ver apps/core/red.py).
# En local no hay ninguno; en Azure App Service hay uno.
PROXIES_DE_CONFIANZA = leer_entero(
    "PROXIES_DE_CONFIANZA", defecto=1 if es_produccion() else 0, minimo=0, maximo=5
)
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
    # Sirve el build de Astro (las pantallas) desde el mismo origen que la API.
    "whitenoise.middleware.WhiteNoiseMiddleware",
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

# Caché en la misma base de datos (sección 12.7): los límites de intentos son
# comunes a todos los workers de gunicorn sin agregar Redis. La tabla la crea
# la migración apps/core/migrations/0001_tabla_cache.py, que corre como
# notia_owner; notia_app no puede crear tablas y solo lee y escribe filas.
TABLA_CACHE = "notia_cache"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": TABLA_CACHE,
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

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

# --- Pantallas: el build de Astro (sección 3, "Mismo origen") ---
# WhiteNoise sirve los archivos de frontend/dist en la raíz del sitio, y la
# API queda bajo /api/. Así las cookies pueden ser SameSite=Strict y no hay
# CORS. En el despliegue, FRONTEND_DIST apunta al dist copiado junto al
# backend. Si la carpeta no existe (por ejemplo, en las pruebas del backend),
# no se sirve nada y Django responde solo la API.
FRONTEND_DIST = Path(leer("FRONTEND_DIST", defecto=str(BASE_DIR.parent / "frontend" / "dist")))
WHITENOISE_ROOT = str(FRONTEND_DIST) if FRONTEND_DIST.is_dir() else None
# /ingresar/ sirve ingresar/index.html, y /ingresar redirige a /ingresar/.
WHITENOISE_INDEX_FILE = True
# Los archivos de /_astro/ llevan un hash en el nombre: se pueden guardar para siempre.
WHITENOISE_IMMUTABLE_FILE_TEST = r"^/_astro/"

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
# Ticket del paso intermedio del 2FA: firmado, de 5 minutos, solo para la
# verificación (sección 8.1).
COOKIE_TICKET_MFA = nombre_cookie_ticket_mfa(produccion=es_produccion())
COOKIE_TICKET_MFA_RUTA = RUTA_COOKIE_TICKET_MFA
MFA_DURACION_DEL_TICKET = timedelta(minutes=5)

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
    # Por omisión se exige una sesión completa: sin 2FA ni cambio de
    # contraseña pendientes. Lo que una sesión restringida puede usar se
    # declara vista por vista.
    "DEFAULT_PERMISSION_CLASSES": ["apps.cuentas.permisos.SesionCompleta"],
    # Límites de peticiones (sección 12.7). Cada vista declara el suyo; se
    # cuentan en la caché en base de datos, común a todos los workers.
    # "mfa" se cuenta por ticket y en ventanas de 300 segundos (5 cada 5 minutos).
    # "usuario" es el límite general por persona de los endpoints de la aplicación.
    "DEFAULT_THROTTLE_RATES": {"login": "10/min", "mfa": "5/300s", "usuario": "300/min"},
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
        # Cada llamada a Azure AI Speech no necesita una línea; los fallos los
        # registra apps/voz/azure.py, sin la llave ni el texto.
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
    },
}

# --- Cuentas ---
DOMINIO_INSTITUCIONAL = leer("DOMINIO_INSTITUCIONAL", defecto="aulaconecta.cl").lower()

# Bloqueo por intentos fallidos (sección 8.1, RS-02): 5 contraseñas
# incorrectas seguidas bloquean la cuenta por 15 minutos.
LOGIN_INTENTOS_ANTES_DE_BLOQUEAR = 5
LOGIN_DURACION_DEL_BLOQUEO = timedelta(minutes=15)

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

# Audios e imágenes de las preguntas: nunca en static ni con URL pública
# (ver apps/core/almacenamiento.py). En local, backend/privado/ (en
# .gitignore); producción lo cambia por el contenedor privado de Blob Storage.
CARPETA_PRIVADA = BASE_DIR / "privado"
_ALMACENAMIENTO_LOCAL = {
    "BACKEND": "apps.core.almacenamiento.AlmacenamientoLocalPrivado",
    "OPTIONS": {"location": str(CARPETA_PRIVADA)},
}
STORAGES = {"default": _ALMACENAMIENTO_LOCAL, "privado": _ALMACENAMIENTO_LOCAL}
