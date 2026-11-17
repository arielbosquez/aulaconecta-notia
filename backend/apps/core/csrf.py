"""Verificación CSRF para la API (RS-05).

Las vistas de Django REST Framework quedan fuera de la revisión automática de
``CsrfViewMiddleware``. Como la sesión de NotIA viaja en cookies, el navegador
la enviaría sola en una petición armada por otro sitio; por eso la API exige
el token CSRF de forma explícita en todo método que modifica datos: la cookie
``csrftoken`` y el mismo valor en la cabecera ``X-CSRFToken``.
"""

import logging

from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import status

registro = logging.getLogger(__name__)


class _RevisionCsrf(CsrfViewMiddleware):
    """La revisión de Django, pero devolviendo el motivo en vez de una respuesta."""

    def _reject(self, request, reason):
        return reason


def _sin_respuesta(request):
    return None


def exigir_csrf(peticion) -> None:
    """Rechaza la petición si modifica datos y no trae un token CSRF válido.

    Los métodos de solo lectura (GET, HEAD, OPTIONS) pasan sin revisión.
    """
    # Se importa aquí porque errores.py carga las vistas de DRF, y estas cargan
    # la clase de autenticación, que usa este módulo.
    from .errores import CODIGO_CSRF, MENSAJE_CSRF, ErrorApi

    # DRF envuelve la petición de Django; la revisión necesita la original.
    original = getattr(peticion, "_request", peticion)
    revision = _RevisionCsrf(_sin_respuesta)
    revision.process_request(original)
    motivo = revision.process_view(original, _sin_respuesta, (), {})
    if motivo:
        # El motivo técnico queda en el servidor; al navegador va un mensaje fijo.
        registro.warning("CSRF rechazado en %s %s: %s", original.method, original.path, motivo)
        raise ErrorApi(CODIGO_CSRF, MENSAJE_CSRF, estado=status.HTTP_403_FORBIDDEN)
