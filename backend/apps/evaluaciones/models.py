"""Evaluaciones, preguntas y alternativas (sección 6 de la arquitectura).

Las reglas que la base de datos puede garantizar por sí sola están como
restricciones (``CheckConstraint`` y ``UniqueConstraint``): tiempos entre 10
y 300 segundos, como máximo una alternativa correcta por pregunta y como
máximo 6 alternativas (orden de 1 a 6, sin repetir). Las que dependen de
contar filas de otra tabla (al menos 2 alternativas y exactamente una
correcta) no se pueden expresar sin triggers, que el proyecto no usa: las
revisa ``apps.evaluaciones.validaciones`` al guardar y al publicar.
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.academico.models import Curso

TIEMPO_MINIMO_SEGUNDOS = 10
TIEMPO_MAXIMO_SEGUNDOS = 300
LARGO_TEXTO_PREGUNTA = 1000
LARGO_TEXTO_ALTERNATIVA = 300
MINIMO_ALTERNATIVAS = 2
MAXIMO_ALTERNATIVAS = 6
PUNTAJE_MAXIMO = 100


class EstadoEvaluacion(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    PUBLICADA = "PUBLICADA", "Publicada"
    CERRADA = "CERRADA", "Cerrada"


class Evaluacion(models.Model):
    """Una prueba de alternativas de un curso.

    Una evaluación publicada no se edita: se crea una nueva versión (copia en
    BORRADOR con ``version + 1`` y ``evaluacion_origen`` apuntando a esta).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="evaluaciones")
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="evaluaciones_creadas"
    )
    titulo = models.CharField("título", max_length=120)
    instrucciones = models.TextField(max_length=2000, blank=True)
    asignatura = models.CharField(max_length=60)
    estado = models.CharField(
        max_length=10, choices=EstadoEvaluacion.choices, default=EstadoEvaluacion.BORRADOR
    )
    version = models.PositiveSmallIntegerField("versión", default=1)
    evaluacion_origen = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="versiones",
        verbose_name="versión anterior",
    )
    # Ventana en que se puede rendir, con la hora del servidor.
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    # Porcentaje de logro con que se obtiene un 4,0.
    exigencia = models.PositiveSmallIntegerField(default=60)
    nota_minima = models.DecimalField(max_digits=2, decimal_places=1, default=Decimal("1.0"))
    nota_maxima = models.DecimalField(max_digits=2, decimal_places=1, default=Decimal("7.0"))
    aleatorizar_preguntas = models.BooleanField(default=True)
    aleatorizar_alternativas = models.BooleanField(default=True)
    publicada_en = models.DateTimeField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evaluación"
        verbose_name_plural = "evaluaciones"
        ordering = ["-inicio"]
        indexes = [models.Index(fields=["curso", "estado"], name="evaluacion_por_curso")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoEvaluacion.values),
                name="evaluacion_estado_conocido",
            ),
            models.CheckConstraint(
                condition=models.Q(fin__gt=models.F("inicio")),
                name="evaluacion_fin_despues_del_inicio",
            ),
            # La fórmula de la nota divide por la exigencia y por (1 - exigencia).
            models.CheckConstraint(
                condition=models.Q(exigencia__gte=1, exigencia__lte=99),
                name="evaluacion_exigencia_entre_1_y_99",
            ),
            # Escala chilena: el 4,0 queda siempre entre la mínima y la máxima.
            models.CheckConstraint(
                condition=models.Q(
                    nota_minima__gte=Decimal("1.0"),
                    nota_minima__lt=Decimal("4.0"),
                    nota_maxima__gt=Decimal("4.0"),
                    nota_maxima__lte=Decimal("7.0"),
                ),
                name="evaluacion_escala_de_notas_valida",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="evaluacion_version_positiva"
            ),
            # Una evaluación publicada o cerrada sabe cuándo se publicó.
            models.CheckConstraint(
                condition=models.Q(estado=EstadoEvaluacion.BORRADOR)
                | models.Q(publicada_en__isnull=False),
                name="evaluacion_publicada_con_fecha",
            ),
            # De cada evaluación sale a lo más una versión nueva.
            models.UniqueConstraint(
                fields=["evaluacion_origen"],
                condition=models.Q(evaluacion_origen__isnull=False),
                name="evaluacion_una_version_siguiente",
            ),
            models.CheckConstraint(
                condition=models.Q(titulo__regex=r"\S"), name="evaluacion_titulo_no_vacio"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.titulo} (v{self.version})"

    @property
    def es_editable(self) -> bool:
        return self.estado == EstadoEvaluacion.BORRADOR


class Pregunta(models.Model):
    """Una pregunta de alternativas.

    El ``texto`` es lo único que el alumno en modalidad NotIA nunca recibe:
    lo escucha en el audio generado al publicar.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evaluacion = models.ForeignKey(
        Evaluacion, on_delete=models.CASCADE, related_name="preguntas"
    )
    orden = models.PositiveSmallIntegerField()
    texto = models.CharField(max_length=LARGO_TEXTO_PREGUNTA)
    tiempo_segundos = models.PositiveSmallIntegerField(default=60)
    puntaje = models.PositiveSmallIntegerField(default=1)
    # Ruta en el almacenamiento privado (sección 12.4); nunca una URL pública.
    imagen = models.CharField(max_length=200, blank=True)
    anulada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "pregunta"
        verbose_name_plural = "preguntas"
        ordering = ["evaluacion", "orden"]
        constraints = [
            models.UniqueConstraint(fields=["evaluacion", "orden"], name="pregunta_orden_unico"),
            models.CheckConstraint(
                condition=models.Q(
                    tiempo_segundos__gte=TIEMPO_MINIMO_SEGUNDOS,
                    tiempo_segundos__lte=TIEMPO_MAXIMO_SEGUNDOS,
                ),
                name="pregunta_tiempo_entre_10_y_300",
            ),
            models.CheckConstraint(
                condition=models.Q(puntaje__gte=1, puntaje__lte=PUNTAJE_MAXIMO),
                name="pregunta_puntaje_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(orden__gte=1), name="pregunta_orden_positivo"
            ),
            models.CheckConstraint(
                condition=models.Q(texto__regex=r"\S"), name="pregunta_texto_no_vacio"
            ),
        ]

    def __str__(self) -> str:
        # Sin el texto: el str de un modelo termina a veces en registros.
        return f"Pregunta {self.orden} de {self.evaluacion_id}"


class Alternativa(models.Model):
    """Una alternativa de una pregunta. Solo una por pregunta es la correcta."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name="alternativas")
    orden = models.PositiveSmallIntegerField()
    texto = models.CharField(max_length=LARGO_TEXTO_ALTERNATIVA)
    es_correcta = models.BooleanField(default=False)

    class Meta:
        verbose_name = "alternativa"
        verbose_name_plural = "alternativas"
        ordering = ["pregunta", "orden"]
        constraints = [
            models.UniqueConstraint(fields=["pregunta", "orden"], name="alternativa_orden_unico"),
            # Orden de 1 a 6 y sin repetir: nunca hay más de 6 alternativas.
            models.CheckConstraint(
                condition=models.Q(orden__gte=1, orden__lte=MAXIMO_ALTERNATIVAS),
                name="alternativa_orden_entre_1_y_6",
            ),
            # Como máximo una correcta por pregunta.
            models.UniqueConstraint(
                fields=["pregunta"],
                condition=models.Q(es_correcta=True),
                name="alternativa_una_sola_correcta",
            ),
            models.CheckConstraint(
                condition=models.Q(texto__regex=r"\S"), name="alternativa_texto_no_vacio"
            ),
        ]

    def __str__(self) -> str:
        return f"Alternativa {self.orden} de {self.pregunta_id}"

