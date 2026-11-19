from django.urls import path

from . import vistas

urlpatterns = [
    path("evaluaciones", vistas.VistaEvaluacionesDelAlumno.as_view(), name="alumno-evaluaciones"),
    path(
        "evaluaciones/<uuid:evaluacion_id>/iniciar",
        vistas.VistaIniciar.as_view(),
        name="alumno-iniciar",
    ),
    path("intentos/<uuid:intento_id>/actual", vistas.VistaActual.as_view(), name="alumno-actual"),
    path(
        "intentos/<uuid:intento_id>/responder",
        vistas.VistaResponder.as_view(),
        name="alumno-responder",
    ),
    path("intentos/<uuid:intento_id>/pasar", vistas.VistaPasar.as_view(), name="alumno-pasar"),
    path("intentos/<uuid:intento_id>/voz", vistas.VistaCambiarVoz.as_view(), name="alumno-voz"),
    path(
        "respuestas/<uuid:ref>/repeticion",
        vistas.VistaRepeticion.as_view(),
        name="alumno-repeticion",
    ),
    path(
        "respuestas/<uuid:ref>/audio", vistas.VistaAudioDeLaPregunta.as_view(), name="alumno-audio"
    ),
    path(
        "respuestas/<uuid:ref>/imagen",
        vistas.VistaImagenDeLaPregunta.as_view(),
        name="alumno-imagen",
    ),
]
