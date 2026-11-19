"""Almacenamiento privado de audios e imágenes (sección 5, "Archivos privados").

Los archivos de las preguntas nunca tienen una URL pública ni adivinable:
solo se entregan a través de endpoints autenticados de Django, que revisan
de quién es el archivo y si ya puede verlo (secciones 7.2 y 12.4).

- En local, una carpeta fuera de los archivos estáticos (``backend/privado/``,
  en ``.gitignore``).
- En Azure, un contenedor privado de Blob Storage al que la aplicación entra
  con su identidad administrada, sin cadenas de conexión ni llaves.
- En las pruebas, memoria.

Todos los almacenamientos de NotIA rechazan ``url()``: si algún código
intentara armar un enlace directo al archivo, falla en vez de exponerlo.
"""

from django.core.files.storage import FileSystemStorage, InMemoryStorage, storages

NOMBRE = "privado"


class SinUrlPublica:
    """Impide armar enlaces directos a los archivos privados."""

    def url(self, name):
        raise NotImplementedError(
            "Los archivos privados no tienen URL: se entregan por un endpoint de la API."
        )


class AlmacenamientoLocalPrivado(SinUrlPublica, FileSystemStorage):
    """Carpeta local, fuera de ``static`` y de lo que sirve WhiteNoise."""

    def __init__(self, **opciones):
        opciones["base_url"] = None
        super().__init__(**opciones)


class AlmacenamientoEnMemoria(SinUrlPublica, InMemoryStorage):
    """Para las pruebas: no deja archivos en el disco."""


def almacenamiento_privado():
    """El almacenamiento ``privado`` de ``STORAGES``.

    Los ``FileField`` lo reciben como función (no como objeto) para que la
    migración no dependa del entorno y cada configuración use el suyo.
    """
    return storages[NOMBRE]
