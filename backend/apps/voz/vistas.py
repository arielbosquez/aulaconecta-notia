"""Voces disponibles y sus audios de muestra (CU-07): ``/api/alumno/voces``."""

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.archivos import respuesta_privada
from apps.core.errores import ErrorApi
from apps.cuentas.permisos import PERMISOS_DEL_ALUMNO

from .proveedores import TIPO_MP3, ErrorDeVoz, voces_disponibles
from .servicios import leer_audio, muestra_de_voz, nombre_de_voz

registro = logging.getLogger(__name__)


class VistaVoces(APIView):
    """Lista las voces con que el alumno puede escuchar sus preguntas."""

    permission_classes = PERMISOS_DEL_ALUMNO

    def get(self, request):
        voces = [
            {
                "id": voz,
                "nombre": nombre_de_voz(voz),
                "muestra_url": f"/api/alumno/voces/{voz}/muestra",
            }
            for voz in voces_disponibles()
        ]
        preferida = request.user.voz_preferida
        if preferida not in voces_disponibles():
            preferida = None
        return Response({"voces": voces, "voz_preferida": preferida})


class VistaMuestraDeVoz(APIView):
    """El audio de ejemplo de una voz, con un texto fijo que no es de ninguna prueba."""

    permission_classes = PERMISOS_DEL_ALUMNO

    def get(self, request, voz: str):
        if voz not in voces_disponibles():
            raise ErrorApi("voz_no_disponible", "Esa voz no está disponible.", estado=404)
        try:
            muestra = muestra_de_voz(voz)
        except ErrorDeVoz:
            registro.warning("No se pudo generar la muestra de una voz.")
            raise ErrorApi(
                "muestra_no_disponible",
                "La muestra de esta voz no está disponible ahora. Inténtalo en un momento.",
                estado=503,
            ) from None
        return respuesta_privada(leer_audio(muestra), TIPO_MP3)
