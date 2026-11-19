from django.urls import path

from . import vistas

urlpatterns = [
    path("voces", vistas.VistaVoces.as_view(), name="alumno-voces"),
    path("voces/<str:voz>/muestra", vistas.VistaMuestraDeVoz.as_view(), name="alumno-voz-muestra"),
]
