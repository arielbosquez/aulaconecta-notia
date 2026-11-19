"""Genera el audio de muestra de cada voz con el proveedor configurado.

    python manage.py generar_muestras

Sirve para dejar las muestras listas antes de una prueba y para comprobar
que la llave y la región de Azure AI Speech funcionan. Muestra solo la voz,
el tamaño y el proveedor: nunca la llave ni la región.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.voz.proveedores import ErrorDeVoz, voces_disponibles
from apps.voz.servicios import muestra_de_voz


class Command(BaseCommand):
    help = "Genera (o confirma) el audio de muestra de cada voz disponible."

    def handle(self, *args, **opciones):
        self.stdout.write(f"Proveedor de voz: {settings.PROVEEDOR_VOZ}")
        fallidas = []
        for voz in voces_disponibles():
            try:
                muestra = muestra_de_voz(voz)
            except ErrorDeVoz as error:
                fallidas.append(voz)
                self.stderr.write(f"{voz}: {error}")
                continue
            generado = f"{timezone.localtime(muestra.generado_en):%d-%m-%Y %H:%M}"
            self.stdout.write(f"{voz}: {muestra.bytes} bytes (generado el {generado})")
        if fallidas:
            raise CommandError(f"No se generaron {len(fallidas)} muestras.")
