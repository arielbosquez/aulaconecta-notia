"""Motor de rendición: el servidor decide qué pregunta ve el alumno (sección 7).

Cada operación que cambia un intento corre en una transacción con el intento
bloqueado (``SELECT … FOR UPDATE``, regla 15): dos pestañas, o dos clics
seguidos, se atienden una después de la otra y nunca sobre un estado viejo.
La segunda ve lo que dejó la primera.

La hora es siempre la del servidor (``ahora``), que llega desde la vista.
Lo que diga el navegador sobre el tiempo no se lee.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from rest_framework import status

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar
from apps.core.errores import ErrorApi

from .models import EstadoIntento, EstadoRespuesta, Intento, Respuesta

MILISEGUNDO = Decimal("0.001")


class PreguntaNoDisponible(ErrorApi):
    def __init__(self):
        super().__init__(
            "pregunta_no_disponible",
            "La pregunta ya no está disponible.",
            estado=status.HTTP_409_CONFLICT,
        )


class AlternativaInvalida(ErrorApi):
    def __init__(self):
        super().__init__(
            "alternativa_invalida",
            "La alternativa elegida no corresponde a esta pregunta.",
            estado=status.HTTP_400_BAD_REQUEST,
        )


@dataclass
class Estado:
    """Lo que el alumno debe ver después de una operación."""

    intento: Intento
    # La pregunta en curso, o ``None`` si el intento terminó.
    respuesta: Respuesta | None


def segundos(delta: timedelta) -> Decimal:
    """Un intervalo en segundos, con precisión de milisegundos."""
    microsegundos = delta // timedelta(microseconds=1)
    return (Decimal(microsegundos) / Decimal(1_000_000)).quantize(MILISEGUNDO)


def restante(respuesta: Respuesta, ahora) -> Decimal:
    """Segundos que le quedan a la pregunta según la hora del servidor.

    Es el tiempo de la pregunta menos lo gastado en tramos anteriores y menos
    el tramo actual, si está en curso. Puede ser negativo.
    """
    tramo = segundos(ahora - respuesta.presentada_en) if respuesta.presentada_en else 0
    return Decimal(respuesta.pregunta.tiempo_segundos) - respuesta.segundos_usados - tramo


def _cerrar_tramo(respuesta: Respuesta, ahora) -> None:
    """Suma el tramo en curso a ``segundos_usados``, sin pasarse del tiempo total."""
    if respuesta.presentada_en is not None:
        total = Decimal(respuesta.pregunta.tiempo_segundos)
        usados = respuesta.segundos_usados + segundos(ahora - respuesta.presentada_en)
        respuesta.segundos_usados = min(total, max(Decimal(0), usados))
        respuesta.presentada_en = None


def _respuestas(intento: Intento):
    return intento.respuestas.select_related("pregunta").order_by("orden_presentacion")


def en_curso(intento: Intento) -> Respuesta | None:
    return _respuestas(intento).filter(estado=EstadoRespuesta.EN_CURSO).first()


def finalizar(intento: Intento, estado: str, ahora) -> None:
    """Cierra el intento: lo que no se respondió queda sin tiempo."""
    intento.estado = estado
    intento.finalizado_en = ahora
    intento.save(update_fields=["estado", "finalizado_en"])
    intento.respuestas.filter(
        estado__in=(EstadoRespuesta.NO_VISTA, EstadoRespuesta.PASADA, EstadoRespuesta.EN_CURSO)
    ).update(estado=EstadoRespuesta.SIN_TIEMPO, presentada_en=None)
    registrar(
        Accion.INTENTO_FINALIZADO,
        actor=intento.alumno,
        objeto=intento,
        detalle={"estado": estado},
    )


def presentar(intento: Intento, ahora, *, despues_de: int | None = None) -> Respuesta | None:
    """La pregunta en curso; si no hay, presenta la siguiente que corresponda.

    - Ronda 1: la primera NO_VISTA en el orden del alumno.
    - Ronda 2: una PASADA a la que le quede tiempo. Se toma la siguiente a
      ``despues_de`` (la que se acaba de pasar o responder) y, si no hay,
      se vuelve a la primera: así pasar una pregunta en la ronda 2 no la
      repite de inmediato mientras haya otras esperando.
    - Si no queda ninguna, el intento termina solo.
    """
    if not intento.en_curso:
        return None
    actual = en_curso(intento)
    if actual is not None:
        return actual

    siguiente = _respuestas(intento).filter(estado=EstadoRespuesta.NO_VISTA).first()
    if siguiente is None:
        pasadas = [
            respuesta
            for respuesta in _respuestas(intento).filter(estado=EstadoRespuesta.PASADA)
            if restante(respuesta, ahora) > 0
        ]
        if pasadas:
            if intento.ronda != 2:
                intento.ronda = 2
                intento.save(update_fields=["ronda"])
            despues = [r for r in pasadas if r.orden_presentacion > (despues_de or 0)]
            siguiente = despues[0] if despues_de is not None and despues else pasadas[0]

    if siguiente is None:
        finalizar(intento, EstadoIntento.FINALIZADO, ahora)
        return None

    siguiente.estado = EstadoRespuesta.EN_CURSO
    siguiente.presentada_en = ahora
    siguiente.save(update_fields=["estado", "presentada_en"])
    return siguiente


def _respuesta_en_curso(intento: Intento, ref) -> Respuesta:
    """La respuesta ``ref`` del intento, si es la que está en curso."""
    respuesta = _respuestas(intento).filter(pk=ref).first()
    if not intento.en_curso or respuesta is None or respuesta.estado != EstadoRespuesta.EN_CURSO:
        raise PreguntaNoDisponible()
    return respuesta


def responder(intento: Intento, ref, alternativa_id, ahora) -> Respuesta | None:
    """Guarda la alternativa elegida y presenta la siguiente pregunta.

    Solo la pregunta en curso y solo con una alternativa de esa pregunta.
    Una respuesta dada no se cambia: la pregunta deja de estar en curso.
    """
    respuesta = _respuesta_en_curso(intento, ref)
    if str(alternativa_id) not in respuesta.orden_alternativas:
        raise AlternativaInvalida()
    _cerrar_tramo(respuesta, ahora)
    respuesta.alternativa_id = alternativa_id
    respuesta.estado = EstadoRespuesta.RESPONDIDA
    respuesta.respondida_en = ahora
    respuesta.save(
        update_fields=["alternativa", "estado", "respondida_en", "segundos_usados", "presentada_en"]
    )
    return presentar(intento, ahora, despues_de=respuesta.orden_presentacion)


def pasar(intento: Intento, ref, ahora) -> Respuesta | None:
    """Deja la pregunta para después, con el tiempo que le quedaba."""
    respuesta = _respuesta_en_curso(intento, ref)
    _cerrar_tramo(respuesta, ahora)
    agotada = respuesta.segundos_usados >= respuesta.pregunta.tiempo_segundos
    respuesta.estado = EstadoRespuesta.SIN_TIEMPO if agotada else EstadoRespuesta.PASADA
    respuesta.save(update_fields=["estado", "segundos_usados", "presentada_en"])
    return presentar(intento, ahora, despues_de=respuesta.orden_presentacion)


def contar_repeticion(intento: Intento, ref, ahora) -> None:
    """Suma una repetición del audio de la pregunta en curso (regla 12)."""
    respuesta = _respuesta_en_curso(intento, ref)
    respuesta.repeticiones_audio += 1
    respuesta.save(update_fields=["repeticiones_audio"])


def bloquear(consulta) -> Intento | None:
    """El intento de la consulta, bloqueado hasta el fin de la transacción.

    ``of=("self",)``: se bloquea solo la fila del intento, no la evaluación
    que se trae con él, para que los intentos de una misma prueba no se
    esperen entre sí.
    """
    return consulta.select_for_update(of=("self",)).select_related("evaluacion").first()


def operar(consulta, operacion) -> Estado | None:
    """Ejecuta ``operacion(intento)`` con el intento bloqueado.

    Si la operación lanza un ``ErrorApi``, lo que ya cambió (por ejemplo, una
    pregunta que se quedó sin tiempo) se confirma igual y el error se lanza
    después de la transacción: un rechazo no deshace el paso del tiempo.
    Devuelve ``None`` si el intento no existe para ese alumno.
    """
    error = None
    with transaction.atomic():
        intento = bloquear(consulta)
        if intento is None:
            return None
        try:
            respuesta = operacion(intento)
        except ErrorApi as rechazo:
            error = rechazo
        else:
            estado = Estado(intento, respuesta if isinstance(respuesta, Respuesta) else None)
    if error is not None:
        raise error
    return estado
