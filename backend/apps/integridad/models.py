"""Eventos de integridad y avisos del alumno (sección 6 de la arquitectura).

Los eventos (salir de la pestaña, intentar copiar…) se registran solo para
que el docente los revise: el sistema no decide nada con ellos ni acusa a
nadie (CU-12). Los tipos son una lista cerrada y no hay ningún campo de
texto: el navegador no puede mandar nada más que el tipo y una duración.
"""


from django.db import models
from django.utils import timezone

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
