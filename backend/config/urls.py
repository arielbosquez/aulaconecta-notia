"""Rutas del proyecto.

Toda la API vive bajo ``/api/``. Cada app agrega aquí sus rutas cuando se
implementa su fase; no hay admin de Django ni vistas con templates.
"""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []
