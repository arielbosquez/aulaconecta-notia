"""Rutas solo para las pruebas: las de autenticación más una vista cualquiera de la API."""

from django.urls import include, path
from rest_framework.response import Response
from rest_framework.views import APIView


class VistaCualquiera(APIView):
    """No declara permisos: usa los que el proyecto aplica por omisión."""

    def get(self, request):
        return Response({"ok": True})

    def post(self, request):
        return Response({"ok": True})


urlpatterns = [
    path("api/auth/", include("apps.cuentas.urls")),
    path("api/cualquiera", VistaCualquiera.as_view()),
]

handler400 = "apps.core.errores.error_400"
handler403 = "apps.core.errores.error_403"
handler404 = "apps.core.errores.error_404"
handler500 = "apps.core.errores.error_500"
