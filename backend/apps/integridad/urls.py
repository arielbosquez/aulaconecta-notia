from django.urls import path

from . import vistas

urlpatterns = [
    path(
        "intentos/<uuid:intento_id>/eventos", vistas.VistaEventos.as_view(), name="alumno-eventos"
    ),
]
