"""Respuestas con archivos privados (audios e imágenes, sección 7.2)."""

from django.http import HttpResponse


def respuesta_privada(contenido: bytes, tipo: str) -> HttpResponse:
    """Entrega un archivo privado sin que quede en ninguna caché.

    - ``Cache-Control: no-store``: ni el navegador ni un proxy lo guardan, así
      que volver a verlo exige pasar otra vez por la revisión de permisos.
    - ``X-Content-Type-Options: nosniff``: el navegador respeta el tipo
      declarado y no lo interpreta como otra cosa.
    - ``Content-Disposition: inline`` sin nombre de archivo.
    """
    respuesta = HttpResponse(contenido, content_type=tipo)
    respuesta["Cache-Control"] = "no-store"
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Content-Disposition"] = "inline"
    respuesta["Content-Length"] = str(len(contenido))
    return respuesta
