"""Lo que entra y lo que sale de los endpoints del alumno (sección 7.2).

La salida se arma a mano, campo por campo, a partir de una lista cerrada:
ningún serializador de modelo copia campos por su cuenta. Así es imposible
que ``es_correcta``, el puntaje, el identificador de la pregunta o el texto
de la pregunta en modalidad NotIA lleguen al navegador por accidente. El
texto sale solo en ``pregunta_para_alumno`` y solo en modalidad normal.

Los serializadores del docente, que sí ven todo eso, van en otro módulo.
"""

from decimal import Decimal
from string import ascii_uppercase

from rest_framework import serializers

from apps.core.serializadores import SerializadorEstricto
from apps.evaluaciones.models import Alternativa, Modalidad
from apps.voz.proveedores import ErrorDeVoz, validar_voz

from .models import EstadoRespuesta, Intento, Respuesta

# --- Entrada ---------------------------------------------------------------------


class CampoVoz(serializers.CharField):
    """Una de las voces de ``VOCES_DISPONIBLES``."""

    def __init__(self, **opciones):
        super().__init__(max_length=60, **opciones)

    def to_internal_value(self, data):
        voz = super().to_internal_value(data)
        try:
            return validar_voz(voz)
        except ErrorDeVoz:
            raise serializers.ValidationError("Esa voz no está disponible.") from None


class SerializadorIniciar(SerializadorEstricto):
    # Obligatoria en NotIA; la modalidad normal no tiene audio y la ignora.
    voz = CampoVoz(required=False, allow_null=True)


class SerializadorRef(SerializadorEstricto):
    ref = serializers.UUIDField()


class SerializadorResponder(SerializadorEstricto):
    ref = serializers.UUIDField()
    alternativa_id = serializers.UUIDField()


class SerializadorVoz(SerializadorEstricto):
    voz = CampoVoz()


# --- Salida ----------------------------------------------------------------------


def _milisegundos(segundos: Decimal) -> int:
    return max(0, int(segundos * 1000))


def alternativas_para_alumno(respuesta: Respuesta) -> list[dict]:
    """Las alternativas en el orden del alumno: id, letra y texto. Nada más."""
    por_id = {
        str(alternativa.id): alternativa
        for alternativa in Alternativa.objects.filter(pregunta_id=respuesta.pregunta_id).only(
            "id", "texto"
        )
    }
    return [
        {
            "id": identificador,
            "letra": ascii_uppercase[posicion],
            "texto": por_id[identificador].texto,
        }
        for posicion, identificador in enumerate(respuesta.orden_alternativas)
        if identificador in por_id
    ]


def pregunta_para_alumno(intento: Intento, respuesta: Respuesta, restante_s: Decimal) -> dict:
    """La pregunta en curso tal como la ve el alumno.

    - NotIA: ``texto`` es siempre ``None`` y la pregunta llega solo como audio.
    - Normal (CU-06): el mismo flujo, con el ``texto`` y sin audio.

    La modalidad que decide es la del intento, copiada de la asignación al
    iniciar: el navegador no puede pedir la otra.
    """
    pregunta = respuesta.pregunta
    normal = intento.modalidad == Modalidad.NORMAL
    return {
        "ref": str(respuesta.id),
        "numero": respuesta.orden_presentacion,
        "total": intento.respuestas.count(),
        "tiempo_total_ms": pregunta.tiempo_segundos * 1000,
        "restante_ms": _milisegundos(restante_s),
        "alternativas": alternativas_para_alumno(respuesta),
        "audio_url": None if normal else f"/api/alumno/respuestas/{respuesta.id}/audio",
        "imagen_url": f"/api/alumno/respuestas/{respuesta.id}/imagen" if pregunta.imagen else None,
        "texto": pregunta.texto if normal else None,
    }


def estado_para_alumno(intento: Intento, respuesta: Respuesta | None, restante_s=None) -> dict:
    """Respuesta de ``actual``, ``responder`` y ``pasar``."""
    cuerpo = {
        "estado": intento.estado,
        "modalidad": intento.modalidad,
        "ronda": intento.ronda,
        "voz": intento.voz or None,
        "pregunta": None,
    }
    if respuesta is not None:
        cuerpo["pregunta"] = pregunta_para_alumno(intento, respuesta, restante_s)
    else:
        # Solo cuántas respondió: ni puntaje ni nota, que se ven cuando el
        # docente publica los resultados.
        cuerpo["resumen"] = {
            "respondidas": intento.respuestas.filter(estado=EstadoRespuesta.RESPONDIDA).count(),
            "total": intento.respuestas.count(),
        }
    return cuerpo
