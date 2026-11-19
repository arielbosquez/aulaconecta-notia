"""Reglas de una evaluación que la base de datos no puede revisar sola.

Una ``CheckConstraint`` solo mira la fila que se guarda. Que una pregunta
tenga al menos 2 alternativas y exactamente una correcta depende de contar
filas de otra tabla, lo que en PostgreSQL exigiría un trigger, y el proyecto
no usa triggers. Estas reglas se revisan aquí: al guardar una pregunta desde
el editor (Fase 3) y antes de publicar, que es lo que garantiza que ningún
alumno rinda una pregunta mal armada.

Los mensajes no incluyen el texto de las preguntas: solo su número.
"""

from django.core.exceptions import ValidationError
from django.db.models import Count, Q

from .models import MAXIMO_ALTERNATIVAS, MINIMO_ALTERNATIVAS, Evaluacion, Pregunta


def errores_de_pregunta(pregunta: Pregunta) -> list[str]:
    """Problemas de las alternativas de una pregunta, o una lista vacía."""
    conteo = pregunta.alternativas.aggregate(
        total=Count("id"), correctas=Count("id", filter=Q(es_correcta=True))
    )
    errores = []
    if not MINIMO_ALTERNATIVAS <= conteo["total"] <= MAXIMO_ALTERNATIVAS:
        errores.append(
            f"La pregunta {pregunta.orden} debe tener entre {MINIMO_ALTERNATIVAS} y "
            f"{MAXIMO_ALTERNATIVAS} alternativas."
        )
    if conteo["correctas"] != 1:
        errores.append(f"La pregunta {pregunta.orden} debe tener exactamente una correcta.")
    return errores


def validar_pregunta(pregunta: Pregunta) -> None:
    """Lanza ``ValidationError`` si la pregunta no se puede rendir así."""
    errores = errores_de_pregunta(pregunta)
    if errores:
        raise ValidationError(errores)


def validar_para_publicar(evaluacion: Evaluacion) -> None:
    """Revisa la evaluación completa antes de publicarla.

    Exige al menos una pregunta y que todas cumplan las reglas de sus
    alternativas. Junta todos los problemas para mostrarlos de una vez.
    """
    preguntas = list(evaluacion.preguntas.order_by("orden"))
    if not preguntas:
        raise ValidationError(["La evaluación debe tener al menos una pregunta."])
    errores = [error for pregunta in preguntas for error in errores_de_pregunta(pregunta)]
    if errores:
        raise ValidationError(errores)
