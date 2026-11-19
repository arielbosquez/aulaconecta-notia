"""Eventos de integridad y avisos del alumno (sección 6 de la arquitectura).

Los eventos (salir de la pestaña, intentar copiar…) se registran solo para
que el docente los revise: el sistema no decide nada con ellos ni acusa a
nadie (CU-12). Los tipos son una lista cerrada y no hay ningún campo de
texto: el navegador no puede mandar nada más que el tipo y una duración.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.evaluaciones.models import Evaluacion
from apps.rendicion.models import Intento, Respuesta

# Un día en milisegundos: ninguna ausencia razonable dura más dentro de una prueba.
DURACION_MAXIMA_MS = 24 * 60 * 60 * 1000


class TipoEvento(models.TextChoices):
    SALIO_DE_PESTANA = "SALIO_DE_PESTANA", "Salió de la pestaña"
    VOLVIO_A_PESTANA = "VOLVIO_A_PESTANA", "Volvió a la pestaña"
    PERDIO_FOCO = "PERDIO_FOCO", "La ventana perdió el foco"
    RECUPERO_FOCO = "RECUPERO_FOCO", "La ventana recuperó el foco"
    SALIO_DE_PANTALLA_COMPLETA = "SALIO_DE_PANTALLA_COMPLETA", "Salió de pantalla completa"
    INTENTO_COPIAR = "INTENTO_COPIAR", "Intentó copiar"
    INTENTO_CORTAR = "INTENTO_CORTAR", "Intentó cortar"
    INTENTO_PEGAR = "INTENTO_PEGAR", "Intentó pegar"
    CLIC_DERECHO = "CLIC_DERECHO", "Clic derecho"
    TECLA_IMPRIMIR_PANTALLA = "TECLA_IMPRIMIR_PANTALLA", "Tecla Imprimir Pantalla"
    RECONEXION = "RECONEXION", "Se reconectó"


class EventoIntegridad(models.Model):
    """Algo que pasó en el navegador durante la prueba, con la hora del servidor."""

    intento = models.ForeignKey(Intento, on_delete=models.CASCADE, related_name="eventos")
    # La pregunta que estaba en curso cuando llegó el evento, según el servidor.
    respuesta = models.ForeignKey(
        Respuesta, on_delete=models.SET_NULL, null=True, blank=True, related_name="eventos"
    )
    tipo = models.CharField(max_length=30, choices=TipoEvento.choices)
    duracion_ms = models.PositiveIntegerField("duración (ms)", null=True, blank=True)
    registrado_en = models.DateTimeField(default=timezone.now)
    revisado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "evento de integridad"
        verbose_name_plural = "eventos de integridad"
        ordering = ["intento", "registrado_en", "id"]
        indexes = [
            # El límite de frecuencia cuenta los eventos del último minuto del intento.
            models.Index(fields=["intento", "registrado_en"], name="evento_por_intento"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoEvento.values), name="evento_tipo_conocido"
            ),
            models.CheckConstraint(
                condition=models.Q(duracion_ms__isnull=True)
                | models.Q(duracion_ms__lte=DURACION_MAXIMA_MS),
                name="evento_duracion_razonable",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tipo} en {self.intento_id}"


class TipoSolicitud(models.TextChoices):
    NINGUNA_VOZ_SIRVE = "NINGUNA_VOZ_SIRVE", "Ninguna voz me acomoda"
    NECESITO_OTRA_MODALIDAD = "NECESITO_OTRA_MODALIDAD", "Necesito otra modalidad"


class EstadoSolicitud(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    ATENDIDA = "ATENDIDA", "Atendida"


class SolicitudAlumno(models.Model):
    """Aviso del alumno al docente desde la pantalla de preparación (CU-08).

    **Sin texto libre** (secciones 6 y 13): si el alumno pudiera escribir,
    podría contar por qué necesita otra modalidad, y eso puede ser un dato
    de salud. Solo hay dos avisos fijos; el docente conversa con el alumno
    fuera del sistema.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alumno = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="solicitudes"
    )
    evaluacion = models.ForeignKey(
        Evaluacion, on_delete=models.CASCADE, related_name="solicitudes"
    )
    tipo = models.CharField(max_length=30, choices=TipoSolicitud.choices)
    estado = models.CharField(
        max_length=10, choices=EstadoSolicitud.choices, default=EstadoSolicitud.PENDIENTE
    )
    creada_en = models.DateTimeField(default=timezone.now)
    atendida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitudes_atendidas",
    )

    class Meta:
        verbose_name = "solicitud del alumno"
        verbose_name_plural = "solicitudes de alumnos"
        ordering = ["-creada_en"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=TipoSolicitud.values),
                name="solicitud_tipo_conocido",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoSolicitud.values),
                name="solicitud_estado_conocido",
            ),
            # Atendida si y solo si se sabe quién la atendió.
            models.CheckConstraint(
                condition=models.Q(estado=EstadoSolicitud.PENDIENTE, atendida_por__isnull=True)
                | models.Q(estado=EstadoSolicitud.ATENDIDA, atendida_por__isnull=False),
                name="solicitud_atendida_por_alguien",
            ),
            # Un mismo aviso pendiente no se repite: insistir no inunda al docente.
            models.UniqueConstraint(
                fields=["alumno", "evaluacion", "tipo"],
                condition=models.Q(estado=EstadoSolicitud.PENDIENTE),
                name="solicitud_pendiente_unica",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tipo} de {self.alumno_id} ({self.estado})"
