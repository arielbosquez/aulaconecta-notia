"""Intentos y respuestas de los alumnos (sección 6 y 7 de la arquitectura).

Al iniciar un intento se crean de una vez todas sus ``Respuesta``, una por
pregunta, con el orden de las preguntas y de las alternativas ya barajado
para ese alumno. Desde ahí, el motor (``motor.py``) solo cambia estados.

Las restricciones de la base de datos sostienen las reglas del motor aunque
el código tuviera un error: una sola pregunta en curso por intento, una
respuesta dada siempre con su alternativa, y un tramo de tiempo abierto
(``presentada_en``) solo mientras la pregunta está en curso.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.evaluaciones.models import Alternativa, Evaluacion, Modalidad, Pregunta


class EstadoIntento(models.TextChoices):
    EN_CURSO = "EN_CURSO", "En curso"
    FINALIZADO = "FINALIZADO", "Finalizado"
    # Terminó porque se cerró la ventana de la prueba.
    EXPIRADO = "EXPIRADO", "Expirado"


class EstadoRespuesta(models.TextChoices):
    NO_VISTA = "NO_VISTA", "No vista"
    EN_CURSO = "EN_CURSO", "En curso"
    PASADA = "PASADA", "Pasada"
    RESPONDIDA = "RESPONDIDA", "Respondida"
    SIN_TIEMPO = "SIN_TIEMPO", "Sin tiempo"


class Intento(models.Model):
    """El intento de un alumno en una evaluación. Hay uno solo por alumno."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluacion = models.ForeignKey(Evaluacion, on_delete=models.PROTECT, related_name="intentos")
    alumno = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="intentos"
    )
    # Copia de la asignación al iniciar: si el docente la cambia después, el
    # intento en curso no cambia de modalidad a mitad de camino.
    modalidad = models.CharField(max_length=6, choices=Modalidad.choices)
    # Vacía en modalidad normal, que no tiene audio.
    voz = models.CharField(max_length=60, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoIntento.choices, default=EstadoIntento.EN_CURSO
    )
    # 1: preguntas en orden. 2: vuelta por las preguntas pasadas.
    ronda = models.PositiveSmallIntegerField(default=1)
    iniciado_en = models.DateTimeField(default=timezone.now)
    finalizado_en = models.DateTimeField(null=True, blank=True)
    reabierto_en = models.DateTimeField(null=True, blank=True)
    reabierto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="intentos_reabiertos",
    )

    class Meta:
        verbose_name = "intento"
        verbose_name_plural = "intentos"
        constraints = [
            models.UniqueConstraint(
                fields=["evaluacion", "alumno"], name="intento_unico_por_alumno"
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoIntento.values),
                name="intento_estado_conocido",
            ),
            models.CheckConstraint(
                condition=models.Q(modalidad__in=Modalidad.values),
                name="intento_modalidad_conocida",
            ),
            models.CheckConstraint(
                condition=models.Q(ronda__in=(1, 2)), name="intento_ronda_1_o_2"
            ),
            # Terminado si y solo si tiene la hora en que terminó.
            models.CheckConstraint(
                condition=(
                    models.Q(estado=EstadoIntento.EN_CURSO, finalizado_en__isnull=True)
                    | (
                        ~models.Q(estado=EstadoIntento.EN_CURSO)
                        & models.Q(finalizado_en__isnull=False)
                    )
                ),
                name="intento_finalizado_con_fecha",
            ),
        ]
        indexes = [models.Index(fields=["alumno", "estado"], name="intento_por_alumno")]

    def __str__(self) -> str:
        return f"Intento {self.id} ({self.estado})"

    @property
    def en_curso(self) -> bool:
        return self.estado == EstadoIntento.EN_CURSO


class Respuesta(models.Model):
    """Lo que pasó con una pregunta dentro de un intento.

    Su ``id`` es el ``ref`` que recibe el navegador: el identificador de la
    pregunta nunca sale del servidor (sección 7.2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    intento = models.ForeignKey(Intento, on_delete=models.CASCADE, related_name="respuestas")
    pregunta = models.ForeignKey(Pregunta, on_delete=models.PROTECT, related_name="respuestas")
    # Posición de la pregunta para este alumno, desde 1.
    orden_presentacion = models.PositiveSmallIntegerField()
    # Identificadores de las alternativas, en el orden en que las ve este alumno.
    orden_alternativas = models.JSONField(default=list)
    estado = models.CharField(
        max_length=10, choices=EstadoRespuesta.choices, default=EstadoRespuesta.NO_VISTA
    )
    # Tiempo ya gastado en tramos cerrados (al pasar o responder).
    segundos_usados = models.DecimalField(max_digits=7, decimal_places=3, default=0)
    # Inicio del tramo actual; solo mientras la pregunta está en curso.
    presentada_en = models.DateTimeField(null=True, blank=True)
    alternativa = models.ForeignKey(
        Alternativa, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    respondida_en = models.DateTimeField(null=True, blank=True)
    repeticiones_audio = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "respuesta"
        verbose_name_plural = "respuestas"
        ordering = ["intento", "orden_presentacion"]
        constraints = [
            models.UniqueConstraint(fields=["intento", "pregunta"], name="respuesta_unica"),
            models.UniqueConstraint(
                fields=["intento", "orden_presentacion"], name="respuesta_orden_unico"
            ),
            # Nunca dos preguntas en curso a la vez en un mismo intento.
            models.UniqueConstraint(
                fields=["intento"],
                condition=models.Q(estado=EstadoRespuesta.EN_CURSO),
                name="respuesta_una_en_curso",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoRespuesta.values),
                name="respuesta_estado_conocido",
            ),
            # Respondida si y solo si tiene alternativa y hora de respuesta.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado=EstadoRespuesta.RESPONDIDA,
                        alternativa__isnull=False,
                        respondida_en__isnull=False,
                    )
                    | (
                        ~models.Q(estado=EstadoRespuesta.RESPONDIDA)
                        & models.Q(alternativa__isnull=True, respondida_en__isnull=True)
                    )
                ),
                name="respuesta_respondida_con_alternativa",
            ),
            # El reloj corre solo para la pregunta en curso.
            models.CheckConstraint(
                condition=(
                    models.Q(estado=EstadoRespuesta.EN_CURSO, presentada_en__isnull=False)
                    | (
                        ~models.Q(estado=EstadoRespuesta.EN_CURSO)
                        & models.Q(presentada_en__isnull=True)
                    )
                ),
                name="respuesta_tramo_solo_en_curso",
            ),
            models.CheckConstraint(
                condition=models.Q(segundos_usados__gte=0), name="respuesta_tiempo_no_negativo"
            ),
            models.CheckConstraint(
                condition=models.Q(orden_presentacion__gte=1), name="respuesta_orden_positivo"
            ),
        ]

    def __str__(self) -> str:
        return f"Respuesta {self.orden_presentacion} de {self.intento_id} ({self.estado})"
