"""Resultado de cada alumno en una evaluación (sección 6 de la arquitectura).

Hay un ``Resultado`` por asignación. El puntaje y la nota los calcula la
función de PostgreSQL ``fn_calcular_resultado`` (sección 9) al terminar el
intento. Un alumno que no rindió nunca recibe una nota automática: su
resultado queda PENDIENTE, y el docente puede marcarlo SIN_NOTA.
"""

from decimal import Decimal

from django.db import models

from apps.evaluaciones.models import AsignacionPrueba
from apps.rendicion.models import Intento


class EstadoResultado(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    CALCULADO = "CALCULADO", "Calculado"
    SIN_NOTA = "SIN_NOTA", "Sin nota"
    # Solo en este estado el alumno ve su nota.
    PUBLICADO = "PUBLICADO", "Publicado"


class Resultado(models.Model):
    asignacion = models.OneToOneField(
        AsignacionPrueba, on_delete=models.CASCADE, related_name="resultado"
    )
    intento = models.OneToOneField(
        Intento, on_delete=models.SET_NULL, null=True, blank=True, related_name="resultado"
    )
    puntaje_obtenido = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    puntaje_total = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    nota = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoResultado.choices, default=EstadoResultado.PENDIENTE
    )
    calculado_en = models.DateTimeField(null=True, blank=True)
    publicado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "resultado"
        verbose_name_plural = "resultados"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(estado__in=EstadoResultado.values),
                name="resultado_estado_conocido",
            ),
            models.CheckConstraint(
                condition=models.Q(nota__isnull=True)
                | models.Q(nota__gte=Decimal("1.0"), nota__lte=Decimal("7.0")),
                name="resultado_nota_entre_1_y_7",
            ),
            models.CheckConstraint(
                condition=models.Q(porcentaje__isnull=True)
                | models.Q(porcentaje__gte=0, porcentaje__lte=100),
                name="resultado_porcentaje_entre_0_y_100",
            ),
            # Un resultado publicado sabe cuándo se publicó.
            models.CheckConstraint(
                condition=~models.Q(estado=EstadoResultado.PUBLICADO)
                | models.Q(publicado_en__isnull=False),
                name="resultado_publicado_con_fecha",
            ),
            # Sin intento no hay nota calculada: nunca una nota automática.
            models.CheckConstraint(
                condition=~models.Q(estado=EstadoResultado.CALCULADO)
                | models.Q(intento__isnull=False, calculado_en__isnull=False),
                name="resultado_calculado_con_intento",
            ),
        ]

    def __str__(self) -> str:
        return f"Resultado de {self.asignacion_id} ({self.estado})"
