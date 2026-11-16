"""Entrada ASGI."""

import os

from django.core.asgi import get_asgi_application

# Igual que en WSGI: sin indicación explícita se usa la configuración de producción.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
