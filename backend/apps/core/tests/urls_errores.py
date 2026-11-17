"""Rutas solo para las pruebas de errores: vistas que fallan a propósito."""

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.urls import path
from rest_framework import exceptions, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.errores import ErrorApi

# Texto ficticio que jamás debe aparecer en una respuesta.
DETALLE_INTERNO = "tabla cuentas_usuario password=clave-ficticia-interna"


class _Datos(serializers.Serializer):
    correo = serializers.EmailField()
    edad = serializers.IntegerField(min_value=1)


class VistaAbierta(APIView):
    permission_classes = [AllowAny]
    fallo: Exception | None = None

    def get(self, request):
        if self.fallo is not None:
            raise self.fallo
        return Response({"ok": True})

    def post(self, request):
        _Datos(data=request.data).is_valid(raise_exception=True)
        return Response({"ok": True})


class VistaProtegida(APIView):
    """Usa los permisos por omisión del proyecto: exige sesión."""

    def get(self, request):
        return Response({"ok": True})


def vista_django_que_falla(request):
    raise RuntimeError(DETALLE_INTERNO)


def vista_django_con_formulario(request):
    return HttpResponse("ok")


def _falla_con(excepcion: Exception):
    return VistaAbierta.as_view(fallo=excepcion)


urlpatterns = [
    path("api/ok", VistaAbierta.as_view()),
    path("api/protegida", VistaProtegida.as_view()),
    path("api/inesperado", _falla_con(RuntimeError(DETALLE_INTERNO))),
    path(
        "api/negocio",
        _falla_con(
            ErrorApi("pregunta_no_disponible", "La pregunta ya no está disponible", estado=409)
        ),
    ),
    path("api/no-encontrado-drf", _falla_con(exceptions.NotFound(DETALLE_INTERNO))),
    path("api/no-encontrado-django", _falla_con(Http404(DETALLE_INTERNO))),
    path("api/denegado-django", _falla_con(PermissionDenied(DETALLE_INTERNO))),
    path("api/limite", _falla_con(exceptions.Throttled(wait=30))),
    path("api/servicio", _falla_con(exceptions.APIException(DETALLE_INTERNO))),
    path("api/django-falla", vista_django_que_falla),
    path("api/django-formulario", vista_django_con_formulario),
]

handler400 = "apps.core.errores.error_400"
handler403 = "apps.core.errores.error_403"
handler404 = "apps.core.errores.error_404"
handler500 = "apps.core.errores.error_500"
