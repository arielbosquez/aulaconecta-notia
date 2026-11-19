"""Eventos de integridad y avisos del alumno (CU-05 y CU-08).

- ``POST /api/alumno/intentos/{id}/eventos``
- ``POST /api/alumno/solicitudes``
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.core.errores import ErrorApi
from apps.core.serializadores import SerializadorEstricto
from apps.evaluaciones.models import AsignacionPrueba, Evaluacion
from apps.rendicion import motor
from apps.rendicion.models import Intento
from apps.rendicion.vistas import ESTADOS_VISIBLES, VistaAlumno, no_encontrado

from .models import (
    DURACION_MAXIMA_MS,
    EstadoSolicitud,
    EventoIntegridad,
    SolicitudAlumno,
    TipoEvento,
    TipoSolicitud,
)

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


# --- Avisos al docente (CU-08) -------------------------------------------------------------


class SerializadorSolicitud(SerializadorEstricto):
    # Sin campo de texto: un campo de más (como "mensaje") se rechaza completo.
    evaluacion = serializers.UUIDField()
    tipo = serializers.ChoiceField(choices=TipoSolicitud.choices)


def _solicitud_para_alumno(solicitud: SolicitudAlumno) -> dict:
    return {
        "id": str(solicitud.id),
        "evaluacion": str(solicitud.evaluacion_id),
        "tipo": solicitud.tipo,
        "estado": solicitud.estado,
        "creada_en": solicitud.creada_en,
    }


class VistaSolicitudes(VistaAlumno):
    """``POST alumno/solicitudes``: "Ninguna voz me acomoda" o "Necesito otra modalidad".

    Solo para una prueba asignada al alumno. Repetir un aviso que sigue
    pendiente devuelve el mismo (200) en vez de crear otro.
    """

    def post(self, request):
        datos = SerializadorSolicitud(data=request.data)
        datos.is_valid(raise_exception=True)
        evaluacion_id, tipo = datos.validated_data["evaluacion"], datos.validated_data["tipo"]

        asignada = AsignacionPrueba.objects.filter(
            evaluacion_id=evaluacion_id,
            alumno=request.user,
            evaluacion__estado__in=ESTADOS_VISIBLES,
        ).exists()
        if not asignada:
            raise no_encontrado(request, Evaluacion, evaluacion_id)

        pendientes = SolicitudAlumno.objects.filter(
            alumno=request.user,
            evaluacion_id=evaluacion_id,
            tipo=tipo,
            estado=EstadoSolicitud.PENDIENTE,
        )
        existente = pendientes.first()
        if existente is not None:
            return Response(_solicitud_para_alumno(existente))
        try:
            with transaction.atomic():
                solicitud = SolicitudAlumno.objects.create(
                    alumno=request.user, evaluacion_id=evaluacion_id, tipo=tipo
                )
        except IntegrityError:
            # Otra petición igual llegó primero: vale la suya.
            return Response(_solicitud_para_alumno(pendientes.get()))
        return Response(_solicitud_para_alumno(solicitud), status=status.HTTP_201_CREATED)
