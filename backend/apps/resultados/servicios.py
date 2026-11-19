"""Cálculo del resultado al terminar un intento (sección 7.1, regla 14, y sección 9)."""

from dataclasses import dataclass
from decimal import Decimal

from django.db import connection
from django.utils import timezone

from apps.evaluaciones.models import AsignacionPrueba
from apps.rendicion.models import Intento

from .models import EstadoResultado, Resultado


@dataclass(frozen=True)
class Calculo:
    puntaje_obtenido: Decimal | None
    puntaje_total: Decimal | None
    porcentaje: Decimal | None
    nota: Decimal | None


def calcular(intento_id) -> Calculo:
    """Llama a ``fn_calcular_resultado`` con un parámetro, nunca armando el SQL.

    Es la única consulta SQL directa de la aplicación (sección 12.3).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT puntaje_obtenido, puntaje_total, porcentaje, nota "
            "FROM public.fn_calcular_resultado(%s)",
            [intento_id],
        )
        fila = cursor.fetchone()
    if fila is None:
        return Calculo(None, None, None, None)
    return Calculo(*fila)


def guardar_resultado(intento: Intento, ahora=None) -> Resultado:
    """Crea o actualiza el resultado del intento en estado CALCULADO.

    Si las notas ya estaban publicadas (por ejemplo, tras reabrir un intento
    en la Fase 3), el resultado sigue publicado con la nota nueva.
    """
    calculo = calcular(intento.id)
    asignacion = AsignacionPrueba.objects.get(
        evaluacion_id=intento.evaluacion_id, alumno_id=intento.alumno_id
    )
    resultado, _ = Resultado.objects.select_for_update().get_or_create(asignacion=asignacion)
    resultado.intento = intento
    resultado.puntaje_obtenido = calculo.puntaje_obtenido
    resultado.puntaje_total = calculo.puntaje_total
    resultado.porcentaje = calculo.porcentaje
    resultado.nota = calculo.nota
    resultado.calculado_en = ahora or timezone.now()
    if resultado.estado != EstadoResultado.PUBLICADO:
        resultado.estado = EstadoResultado.CALCULADO
    resultado.save()
    return resultado
