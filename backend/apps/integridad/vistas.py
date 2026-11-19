"""Eventos de integridad del alumno: ``POST /api/alumno/intentos/{id}/eventos``."""

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.core.errores import ErrorApi
from apps.core.serializadores import SerializadorEstricto
from apps.rendicion import motor
from apps.rendicion.models import Intento
from apps.rendicion.vistas import VistaAlumno, no_encontrado

from .models import DURACION_MAXIMA_MS, EventoIntegridad, TipoEvento

# Sección 11: hasta 20 eventos por envío y 60 por minuto por intento.
EVENTOS_POR_ENVIO = 20
EVENTOS_POR_MINUTO = 60
VENTANA_DEL_LIMITE = timedelta(minutes=1)


class SerializadorEvento(SerializadorEstricto):
    # Solo un tipo de la lista cerrada y una duración: ningún texto libre.
    tipo = serializers.ChoiceField(choices=TipoEvento.choices)
    duracion_ms = serializers.IntegerField(
        min_value=0, max_value=DURACION_MAXIMA_MS, required=False, allow_null=True
    )


class SerializadorLoteDeEventos(SerializadorEstricto):
    eventos = serializers.ListField(
        child=SerializadorEvento(), min_length=1, max_length=EVENTOS_POR_ENVIO
    )


class DemasiadosEventos(ErrorApi):
    def __init__(self):
        super().__init__(
            "demasiados_eventos",
            "Se enviaron demasiados eventos. Espera un momento.",
            estado=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class VistaEventos(VistaAlumno):
    """Registra un lote de eventos del intento en curso.

    - Hora del servidor: el navegador no informa cuándo pasó cada evento.
    - La pregunta asociada la decide el servidor (la que está en curso).
    - Límite de frecuencia exacto: con el intento bloqueado se cuentan los
      eventos del último minuto, y un lote que lo supere se rechaza completo
      con 429. Así el conteo es el mismo para todos los workers y no depende
      de la caché.
    """

    def post(self, request, intento_id):
        datos = SerializadorLoteDeEventos(data=request.data)
        datos.is_valid(raise_exception=True)
        eventos = datos.validated_data["eventos"]
        ahora = timezone.now()

        def registrar(intento):
            motor.sincronizar(intento, ahora)
            if not intento.en_curso:
                raise ErrorApi(
                    "intento_terminado",
                    "La prueba ya terminó.",
                    estado=status.HTTP_409_CONFLICT,
                )
            recientes = EventoIntegridad.objects.filter(
                intento=intento, registrado_en__gt=ahora - VENTANA_DEL_LIMITE
            ).count()
            if recientes + len(eventos) > EVENTOS_POR_MINUTO:
                raise DemasiadosEventos()
            actual = motor.en_curso(intento)
            EventoIntegridad.objects.bulk_create(
                EventoIntegridad(
                    intento=intento,
                    respuesta=actual,
                    tipo=evento["tipo"],
                    duracion_ms=evento.get("duracion_ms"),
                    registrado_en=ahora,
                )
                for evento in eventos
            )

        consulta = Intento.objects.filter(pk=intento_id, alumno=request.user)
        if motor.operar(consulta, registrar) is None:
            raise no_encontrado(request, Intento, intento_id)
        return Response({"registrados": len(eventos)}, status=status.HTTP_201_CREATED)
