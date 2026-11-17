"""Manejo de errores genérico de la API (RS-18).

Todas las respuestas de error tienen la forma
``{"codigo": "...", "mensaje": "..."}``, en español y sin trazas. El detalle
técnico (tipo de excepción, traza) queda solo en los registros del servidor.

Hay dos puertas de entrada:

- ``manejador_de_excepciones``: para las vistas de Django REST Framework.
- ``error_400`` … ``error_500`` y ``error_csrf``: para lo que Django resuelve
  antes de llegar a una vista (ruta inexistente, CSRF, fallo inesperado).
"""

import logging

from django.core.exceptions import PermissionDenied as PermisoDenegadoDjango
from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import set_rollback

registro = logging.getLogger(__name__)

# Código y mensaje fijos por estado HTTP. Lo que diga la excepción original
# no se muestra: puede traer nombres de tablas, rutas o datos de otra persona.
ERRORES_POR_ESTADO = {
    400: ("solicitud_invalida", "La solicitud no es válida."),
    401: ("no_autenticado", "Debes iniciar sesión para continuar."),
    403: ("sin_permiso", "No tienes permiso para realizar esta acción."),
    404: ("no_encontrado", "No encontramos lo que buscas."),
    405: ("metodo_no_permitido", "Esta operación no está disponible."),
    406: ("formato_no_aceptado", "No podemos responder en el formato solicitado."),
    415: ("formato_no_soportado", "El formato de los datos enviados no es válido."),
    429: (
        "demasiadas_solicitudes",
        "Demasiados intentos. Espera un momento y vuelve a intentarlo.",
    ),
    500: ("error_interno", "Ocurrió un error inesperado. Inténtalo de nuevo más tarde."),
}

CODIGO_DATOS_INVALIDOS = "datos_invalidos"
MENSAJE_DATOS_INVALIDOS = "Revisa los datos ingresados."
CODIGO_CSRF = "csrf_invalido"
MENSAJE_CSRF = "La página estuvo abierta mucho tiempo. Recárgala y vuelve a intentarlo."


class ErrorApi(exceptions.APIException):
    """Error de negocio con un código y un mensaje pensados para el usuario.

    Es la única excepción cuyo mensaje llega tal cual al navegador, así que
    el mensaje se escribe siempre en el código, nunca a partir de datos.

    Ejemplo: ``raise ErrorApi("pregunta_no_disponible", "La pregunta ya no
    está disponible", estado=409)``.
    """

    def __init__(self, codigo: str, mensaje: str, *, estado: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(detail=mensaje, code=codigo)
        self.codigo = codigo
        self.mensaje = mensaje
        self.status_code = estado


def cuerpo_de_error(estado: int) -> dict[str, str]:
    """Cuerpo genérico para un estado HTTP de error."""
    genericos = ERRORES_POR_ESTADO[500] if estado >= 500 else ERRORES_POR_ESTADO[400]
    codigo, mensaje = ERRORES_POR_ESTADO.get(estado, genericos)
    return {"codigo": codigo, "mensaje": mensaje}


def _ruta(peticion) -> str:
    """Método y ruta de la petición, sin parámetros ni cuerpo."""
    if peticion is None:
        return "-"
    return f"{getattr(peticion, 'method', '-')} {getattr(peticion, 'path', '-')}"


def manejador_de_excepciones(excepcion, contexto):
    """``EXCEPTION_HANDLER`` de DRF: convierte toda excepción en un error genérico."""
    peticion = (contexto or {}).get("request")

    if isinstance(excepcion, Http404):
        excepcion = exceptions.NotFound()
    elif isinstance(excepcion, PermisoDenegadoDjango):
        excepcion = exceptions.PermissionDenied()

    cabeceras = {}

    if isinstance(excepcion, ErrorApi):
        estado = excepcion.status_code
        cuerpo = {"codigo": excepcion.codigo, "mensaje": excepcion.mensaje}
    elif isinstance(excepcion, exceptions.ValidationError):
        estado = excepcion.status_code
        # El detalle indica qué campo corregir; lo generan los serializadores.
        cuerpo = {
            "codigo": CODIGO_DATOS_INVALIDOS,
            "mensaje": MENSAJE_DATOS_INVALIDOS,
            "detalle": excepcion.detail,
        }
    elif isinstance(excepcion, exceptions.APIException):
        estado = excepcion.status_code
        cuerpo = cuerpo_de_error(estado)
        if getattr(excepcion, "auth_header", None):
            cabeceras["WWW-Authenticate"] = excepcion.auth_header
        if getattr(excepcion, "wait", None):
            cabeceras["Retry-After"] = str(int(excepcion.wait) + 1)
        if estado >= 500:
            registro.error("Error del servidor en %s", _ruta(peticion), exc_info=excepcion)
    else:
        estado = status.HTTP_500_INTERNAL_SERVER_ERROR
        cuerpo = cuerpo_de_error(estado)
        registro.error("Error no controlado en %s", _ruta(peticion), exc_info=excepcion)

    # Si la petición iba dentro de una transacción, no se confirma nada.
    set_rollback()
    return Response(cuerpo, status=estado, headers=cabeceras)


def _respuesta(estado: int, cuerpo: dict[str, str] | None = None) -> JsonResponse:
    return JsonResponse(
        cuerpo or cuerpo_de_error(estado),
        status=estado,
        json_dumps_params={"ensure_ascii": False},
    )


def error_400(request, exception=None):
    return _respuesta(400)


def error_403(request, exception=None):
    return _respuesta(403)


def error_404(request, exception=None):
    return _respuesta(404)


def error_500(request):
    # Django ya registró la traza en el servidor antes de llamar aquí.
    return _respuesta(500)


def error_csrf(request, reason=""):
    """``CSRF_FAILURE_VIEW``: el motivo técnico se registra, no se muestra."""
    registro.warning("CSRF rechazado en %s: %s", _ruta(request), reason)
    return _respuesta(403, {"codigo": CODIGO_CSRF, "mensaje": MENSAJE_CSRF})
