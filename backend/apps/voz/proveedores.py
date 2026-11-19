"""Proveedores de voz: convierten el texto de una pregunta en audio MP3.

Hay dos implementaciones de ``ProveedorVoz`` (sección 12.5):

- ``ProveedorPrueba``: genera un MP3 corto de silencio, sin red. Lo usan las
  pruebas automáticas y el desarrollo sin llave de Azure.
- ``ProveedorAzure`` (``azure.py``): Azure AI Speech por REST.

``PROVEEDOR_VOZ`` elige cuál se usa. Solo se llama al proveedor al publicar
una evaluación y al generar los audios de muestra: durante la prueba, el
alumno recibe audios ya guardados.
"""

from abc import ABC, abstractmethod

from django.conf import settings

TIPO_MP3 = "audio/mpeg"


class ErrorDeVoz(Exception):
    """No se pudo generar un audio.

    El mensaje es siempre fijo y pensado para quien publica: nunca incluye la
    llave, la respuesta de Azure ni el texto de la pregunta.
    """


def voces_disponibles() -> tuple[str, ...]:
    return tuple(settings.VOCES_DISPONIBLES)


def validar_voz(voz: str) -> str:
    """Devuelve la voz si está en ``VOCES_DISPONIBLES``; si no, lanza ``ErrorDeVoz``."""
    if voz not in voces_disponibles():
        raise ErrorDeVoz("La voz pedida no está disponible.")
    return voz


class ProveedorVoz(ABC):
    """Convierte un texto en un audio MP3 con una de las voces disponibles."""

    @abstractmethod
    def sintetizar(self, texto: str, voz: str) -> bytes:
        """Devuelve el MP3 del texto leído con la voz, o lanza ``ErrorDeVoz``."""


# --- Proveedor de prueba ---------------------------------------------------------
#
# Un MP3 válido de silencio, armado a mano: cuadros MPEG-1 Layer III mono de
# 32 kbit/s a 48 kHz, sin CRC. Cada cuadro mide 144 * 32000 / 48000 = 96 bytes
# y dura 1152 / 48000 = 24 ms. Con la información lateral en cero, el cuadro
# no trae datos de audio y el reproductor lo decodifica como silencio.
CABECERA_CUADRO = bytes((0xFF, 0xFB, 0x14, 0xC0))
BYTES_POR_CUADRO = 96
MILISEGUNDOS_POR_CUADRO = 24
CUADRO_SILENCIO = CABECERA_CUADRO + bytes(BYTES_POR_CUADRO - len(CABECERA_CUADRO))

# Duración aproximada de la lectura: unos 15 caracteres por segundo.
CARACTERES_POR_SEGUNDO = 15
SEGUNDOS_MINIMOS = 1
SEGUNDOS_MAXIMOS = 30


def mp3_de_silencio(segundos: float) -> bytes:
    cuadros = max(1, round(segundos * 1000 / MILISEGUNDOS_POR_CUADRO))
    return CUADRO_SILENCIO * cuadros


class ProveedorPrueba(ProveedorVoz):
    """Audio sintético sin red, para las pruebas y para desarrollar sin llave.

    El audio no contiene el texto ni la voz, solo silencio de una duración
    parecida a la que tendría la lectura real.
    """

    def sintetizar(self, texto: str, voz: str) -> bytes:
        validar_voz(voz)
        if not texto.strip():
            raise ErrorDeVoz("No hay texto que leer.")
        segundos = min(
            SEGUNDOS_MAXIMOS, max(SEGUNDOS_MINIMOS, len(texto) / CARACTERES_POR_SEGUNDO)
        )
        return mp3_de_silencio(segundos)


def obtener_proveedor() -> ProveedorVoz:
    """El proveedor que indica ``PROVEEDOR_VOZ``."""
    if settings.PROVEEDOR_VOZ == "azure":
        from .azure import ProveedorAzure

        return ProveedorAzure.desde_settings()
    return ProveedorPrueba()
