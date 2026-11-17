"""Rutas del proyecto.

Toda la API vive bajo ``/api/``. Cada app agrega aquí sus rutas cuando se
implementa su fase; no hay admin de Django ni vistas con templates.
"""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []

# Errores que Django resuelve fuera de una vista (ruta inexistente, fallo
# inesperado): JSON genérico en español, sin trazas ni páginas HTML.
handler400 = "apps.core.errores.error_400"
handler403 = "apps.core.errores.error_403"
handler404 = "apps.core.errores.error_404"
handler500 = "apps.core.errores.error_500"
