"""Configuración común a todos los entornos.

Aquí solo hay valores no sensibles. Las llaves y contraseñas llegan por
variables de entorno y cada entorno decide qué hacer si faltan.
"""

import os
from pathlib import Path

# Carpeta backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Cada entorno define su propia llave; base nunca trae una escrita.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

DEBUG = False

ALLOWED_HOSTS: list[str] = []

# Django solo expone la API REST: no se instalan el admin, las sesiones,
# los mensajes ni los archivos estáticos de Django.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "rest_framework",
]

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
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "notia"),
        "USER": os.environ.get("DB_USER", "notia_app"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "OPTIONS": {
            "sslmode": os.environ.get("DB_SSLMODE", "prefer"),
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
