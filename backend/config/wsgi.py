"""Entrada WSGI (gunicorn en App Service)."""

import os

from django.core.wsgi import get_wsgi_application

# Un servidor que no indique su configuración arranca con la de producción,
# que es la más estricta.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
