"""Configuración de NotIA separada por entorno.

- ``base``: lo común a todos los entornos.
- ``dev``: desarrollo local.
- ``test``: pruebas automáticas.
- ``prod``: producción (Azure App Service).

No existe una configuración por defecto: cada punto de entrada indica la suya
con ``DJANGO_SETTINGS_MODULE``.
"""
