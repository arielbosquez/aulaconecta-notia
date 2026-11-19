"""Audios generados: uno por pregunta y voz, y uno de muestra por voz.

Los archivos viven en el almacenamiento privado con un nombre aleatorio. El
nombre no dice de qué pregunta, voz ni evaluación es: aunque alguien viera la
lista del contenedor, no podría adivinar cuál pedir.
"""

import uuid

from django.db import models
from django.utils import timezone

from apps.core.almacenamiento import almacenamiento_privado
from apps.evaluaciones.models import Pregunta

LARGO_VOZ = 60


def ruta_aleatoria_de_audio(instancia, nombre_original: str) -> str:
    """``audios/<uuid>.mp3``: el nombre que mande quien sea se descarta."""
    return f"audios/{uuid.uuid4().hex}.mp3"


class AudioPregunta(models.Model):
    """El audio de una pregunta leída con una voz.

    ``hash_contenido`` es el SHA-256 de la voz y el texto: si ninguno cambió,
    el audio ya existe y no se vuelve a pedir a Azure (sección 12.5).
    """

    pregunta = models.ForeignKey(Pregunta, on_delete=models.CASCADE, related_name="audios")
    voz = models.CharField(max_length=LARGO_VOZ)
    archivo = models.FileField(
        storage=almacenamiento_privado, upload_to=ruta_aleatoria_de_audio, max_length=200
    )
    hash_contenido = models.CharField(max_length=64)
    bytes = models.PositiveIntegerField()
    generado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "audio de pregunta"
        verbose_name_plural = "audios de preguntas"
        constraints = [
            models.UniqueConstraint(fields=["pregunta", "voz"], name="audio_unico_por_voz"),
            models.CheckConstraint(
                condition=models.Q(bytes__gt=0), name="audio_pregunta_no_vacio"
            ),
        ]
        indexes = [models.Index(fields=["hash_contenido"], name="audio_por_hash")]

    def __str__(self) -> str:
        return f"Audio {self.voz} de {self.pregunta_id}"


class AudioMuestra(models.Model):
    """Audio corto de ejemplo de una voz.

    Con él el alumno elige la voz antes de empezar, sin escuchar ninguna
    pregunta real (CU-07).
    """

    voz = models.CharField(max_length=LARGO_VOZ, unique=True)
    archivo = models.FileField(
        storage=almacenamiento_privado, upload_to=ruta_aleatoria_de_audio, max_length=200
    )
    hash_contenido = models.CharField(max_length=64)
    bytes = models.PositiveIntegerField()
    generado_en = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "audio de muestra"
        verbose_name_plural = "audios de muestra"
        constraints = [
            models.CheckConstraint(condition=models.Q(bytes__gt=0), name="audio_muestra_no_vacio"),
        ]

    def __str__(self) -> str:
        return f"Muestra de {self.voz}"
