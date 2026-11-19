"""Creación de un intento con el orden barajado por alumno (sección 7.1, regla 2)."""

import secrets

from django.utils import timezone

from apps.evaluaciones.models import AsignacionPrueba, Modalidad

from .models import Intento, Respuesta

# Generador del sistema operativo: el orden de un alumno no se puede deducir
# del de otro ni repetir conociendo una semilla.
_azar = secrets.SystemRandom()


def barajar(elementos: list) -> list:
    """Una copia de la lista en un orden al azar."""
    copia = list(elementos)
    _azar.shuffle(copia)
    return copia


def crear_intento(asignacion: AsignacionPrueba, *, voz: str, ahora=None) -> Intento:
    """Crea el intento y todas sus respuestas.

    Si la evaluación lo indica, el orden de las preguntas y el de las
    alternativas de cada una se barajan para este alumno. Quien llama ya
    revisó las reglas de inicio (sección 7.1, regla 1) y tiene bloqueada la
    asignación.
    """
    evaluacion = asignacion.evaluacion
    ahora = ahora or timezone.now()
    intento = Intento.objects.create(
        evaluacion=evaluacion,
        alumno=asignacion.alumno,
        modalidad=asignacion.modalidad,
        voz=voz if asignacion.modalidad == Modalidad.NOTIA else "",
        iniciado_en=ahora,
    )

    preguntas = list(evaluacion.preguntas.order_by("orden").prefetch_related("alternativas"))
    if evaluacion.aleatorizar_preguntas:
        preguntas = barajar(preguntas)

    respuestas = []
    for posicion, pregunta in enumerate(preguntas, start=1):
        alternativas = [
            str(alternativa.id)
            for alternativa in sorted(pregunta.alternativas.all(), key=lambda a: a.orden)
        ]
        if evaluacion.aleatorizar_alternativas:
            alternativas = barajar(alternativas)
        respuestas.append(
            Respuesta(
                intento=intento,
                pregunta=pregunta,
                orden_presentacion=posicion,
                orden_alternativas=alternativas,
            )
        )
    Respuesta.objects.bulk_create(respuestas)
    return intento
