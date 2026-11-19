from django.urls import path

from . import vistas

urlpatterns = [
    path("resultados", vistas.VistaResultadosDelAlumno.as_view(), name="alumno-resultados"),
]
