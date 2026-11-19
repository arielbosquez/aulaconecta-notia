"""Generación y reutilización de audios (sección 12.5).

Un audio se identifica por el SHA-256 de su voz y su texto
(``hash_contenido``). Si ya existe uno con el mismo hash, se reutiliza su
archivo en vez de volver a llamar a Azure: así una nueva versión de una
evaluación, o volver a publicar tras un fallo, no paga dos veces el mismo
audio.

La generación en paralelo de todos los audios al publicar llega con la
publicación (Fase 3); aquí está la pieza que genera uno.
"""

import hashlib
import re

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.evaluaciones.models import Pregunta

from .models import AudioMuestra, AudioPregunta
from .proveedores import ErrorDeVoz, ProveedorVoz, obtener_proveedor, validar_voz

TEXTO_MUESTRA = "Hola, esta es la voz que leerá tus preguntas."

_PATRON_NOMBRE_VOZ = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-(?P<nombre>[A-Za-z]+?)(?:Neural)?$")


def nombre_de_voz(voz: str) -> str:
    """Nombre para mostrar: ``es-CL-CatalinaNeural`` → ``Catalina``."""
    coincidencia = _PATRON_NOMBRE_VOZ.match(voz)
    return coincidencia.group("nombre") if coincidencia else voz


def hash_de_contenido(voz: str, texto: str) -> str:
    return hashlib.sha256(f"{voz}\n{texto}".encode()).hexdigest()


def _archivo_reutilizable(hash_contenido: str) -> str | None:
    """Nombre de un archivo ya generado con la misma voz y el mismo texto."""
    for modelo in (AudioPregunta, AudioMuestra):
        nombre = (
            modelo.objects.filter(hash_contenido=hash_contenido)
            .values_list("archivo", flat=True)
            .first()
        )
        if nombre:
            return nombre
    return None


def _guardar_mp3(campo, contenido: bytes) -> None:
    if not contenido:
        raise ErrorDeVoz("El proveedor de voz respondió un audio vacío.")
    campo.save("audio.mp3", ContentFile(contenido), save=False)


def audio_de_pregunta(
    pregunta: Pregunta, voz: str, proveedor: ProveedorVoz | None = None
) -> AudioPregunta:
    """El audio de la pregunta con esa voz; lo genera solo si hace falta."""
    validar_voz(voz)
    hash_contenido = hash_de_contenido(voz, pregunta.texto)
    actual = AudioPregunta.objects.filter(pregunta=pregunta, voz=voz).first()
    if actual is not None and actual.hash_contenido == hash_contenido:
        return actual

    audio = actual or AudioPregunta(pregunta=pregunta, voz=voz)
    reutilizable = _archivo_reutilizable(hash_contenido)
    if reutilizable:
        audio.archivo.name = reutilizable
        audio.bytes = audio.archivo.size
    else:
        contenido = (proveedor or obtener_proveedor()).sintetizar(pregunta.texto, voz)
        _guardar_mp3(audio.archivo, contenido)
        audio.bytes = len(contenido)
    audio.hash_contenido = hash_contenido
    audio.generado_en = timezone.now()
    audio.save()
    return audio


def muestra_de_voz(voz: str, proveedor: ProveedorVoz | None = None) -> AudioMuestra:
    """El audio de muestra de la voz; la primera vez lo genera.

    El texto es fijo y no tiene nada de ninguna prueba. Si dos alumnos piden
    la misma muestra a la vez, la base de datos deja una sola.
    """
    validar_voz(voz)
    hash_contenido = hash_de_contenido(voz, TEXTO_MUESTRA)
    actual = AudioMuestra.objects.filter(voz=voz).first()
    if actual is not None and actual.hash_contenido == hash_contenido:
        return actual

    contenido = (proveedor or obtener_proveedor()).sintetizar(TEXTO_MUESTRA, voz)
    muestra = actual or AudioMuestra(voz=voz)
    _guardar_mp3(muestra.archivo, contenido)
    muestra.bytes = len(contenido)
    muestra.hash_contenido = hash_contenido
    muestra.generado_en = timezone.now()
    try:
        with transaction.atomic():
            muestra.save()
    except IntegrityError:
        # Otra petición la guardó primero: vale la suya.
        muestra.archivo.delete(save=False)
        return AudioMuestra.objects.get(voz=voz)
    return muestra


def leer_audio(audio: AudioPregunta | AudioMuestra) -> bytes:
    with audio.archivo.open("rb") as archivo:
        return archivo.read()
