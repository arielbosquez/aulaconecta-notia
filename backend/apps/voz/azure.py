"""Proveedor de Azure AI Speech por REST (sección 12.5, RS-12).

Lo que protege este módulo:

- **Inyección de SSML.** El texto de la pregunta lo escribe un docente y se
  inserta dentro de un documento XML. Se escapa como XML antes de armarlo,
  así un ``<`` o un ``&`` se leen como texto y no cambian la voz, el idioma
  ni agregan etiquetas. La voz sale de la lista cerrada ``VOCES_DISPONIBLES``.
- **Un tercero que no responde o responde mal.** Tiempo de espera de 10
  segundos, hasta 2 reintentos con espera creciente (solo ante fallas
  pasajeras), y la respuesta se acepta solo si es ``audio/mpeg``, tiene un
  tamaño razonable y empieza como un MP3.
- **La llave.** Viaja solo en la cabecera ``Ocp-Apim-Subscription-Key`` y no
  aparece en ningún mensaje de error, registro ni representación del objeto.
  La región forma parte de la URL, así que solo se aceptan letras y números.
"""

import logging
import re
import time
from collections.abc import Callable
from xml.sax.saxutils import escape, quoteattr

import httpx
from django.conf import settings

from .proveedores import TIPO_MP3, ErrorDeVoz, ProveedorVoz, validar_voz

registro = logging.getLogger(__name__)

URL_SINTESIS = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
FORMATO_SALIDA = "audio-24khz-48kbitrate-mono-mp3"
SEGUNDOS_DE_ESPERA = 10.0
REINTENTOS = 2
# Espera antes de cada reintento: crece en cada vuelta.
ESPERAS_ENTRE_INTENTOS = (0.5, 1.5)
# A 48 kbit/s, 5 MB son más de 13 minutos de audio: una pregunta nunca llega.
BYTES_MAXIMOS = 5 * 1024 * 1024
# Fallas pasajeras de Azure: vale la pena volver a intentar.
ESTADOS_REINTENTABLES = frozenset({408, 429, 500, 502, 503, 504})

PATRON_REGION = re.compile(r"[a-z0-9]{2,40}")
# Ejemplo: es-CL-CatalinaNeural. De aquí sale también el idioma del SSML.
PATRON_VOZ = re.compile(r"(?P<idioma>[a-z]{2,3}-[A-Z]{2})-[A-Za-z0-9]{1,60}")
# Caracteres de control que XML 1.0 no admite ni escapados.
PATRON_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

# Un MP3 empieza con una etiqueta ID3 o con la sincronización de un cuadro.
_INICIO_ID3 = b"ID3"


def _parece_mp3(contenido: bytes) -> bool:
    if contenido.startswith(_INICIO_ID3):
        return True
    return len(contenido) >= 2 and contenido[0] == 0xFF and contenido[1] & 0xE0 == 0xE0


def armar_ssml(texto: str, voz: str) -> str:
    """Documento SSML con el texto escapado como XML.

    ``escape`` cambia ``&``, ``<`` y ``>``, y aquí también las comillas; la voz
    va como atributo con ``quoteattr``. Ningún carácter del texto puede
    cerrar la etiqueta ``voice`` ni abrir otra.
    """
    validar_voz(voz)
    coincidencia = PATRON_VOZ.fullmatch(voz)
    if coincidencia is None:
        raise ErrorDeVoz("La voz pedida no está disponible.")
    limpio = PATRON_CONTROL.sub(" ", texto).strip()
    if not limpio:
        raise ErrorDeVoz("No hay texto que leer.")
    contenido = escape(limpio, {'"': "&quot;", "'": "&apos;"})
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f"xml:lang={quoteattr(coincidencia.group('idioma'))}>"
        f"<voice name={quoteattr(voz)}>{contenido}</voice>"
        "</speak>"
    )


class _FallaPasajera(Exception):
    """Falla que justifica un reintento. Nunca sale de este módulo."""


class ProveedorAzure(ProveedorVoz):
    """Azure AI Speech con voces neuronales de español de Chile."""

    def __init__(
        self,
        *,
        llave: str,
        region: str,
        transporte: httpx.BaseTransport | None = None,
        esperar: Callable[[float], None] = time.sleep,
    ):
        if not llave:
            raise ErrorDeVoz("Falta configurar la llave de Azure AI Speech.")
        if not PATRON_REGION.fullmatch(region or ""):
            raise ErrorDeVoz("La región de Azure AI Speech no es válida.")
        self.__llave = llave
        self.region = region
        self._transporte = transporte
        self._esperar = esperar

    @classmethod
    def desde_settings(cls) -> "ProveedorAzure":
        return cls(llave=settings.AZURE_SPEECH_KEY, region=settings.AZURE_SPEECH_REGION)

    def __repr__(self) -> str:
        # Sin la llave: un objeto puede terminar impreso en una traza.
        return f"ProveedorAzure(region={self.region!r})"

    @property
    def url(self) -> str:
        return URL_SINTESIS.format(region=self.region)

    def sintetizar(self, texto: str, voz: str) -> bytes:
        cuerpo = armar_ssml(texto, voz).encode("utf-8")
        cabeceras = {
            "Ocp-Apim-Subscription-Key": self.__llave,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": FORMATO_SALIDA,
            "User-Agent": "NotIA",
        }
        with httpx.Client(
            timeout=httpx.Timeout(SEGUNDOS_DE_ESPERA),
            transport=self._transporte,
            follow_redirects=False,
        ) as cliente:
            for intento in range(REINTENTOS + 1):
                if intento:
                    self._esperar(ESPERAS_ENTRE_INTENTOS[intento - 1])
                try:
                    return self._pedir(cliente, cuerpo, cabeceras)
                except _FallaPasajera as falla:
                    registro.warning(
                        "Azure AI Speech falló (intento %s de %s): %s",
                        intento + 1,
                        REINTENTOS + 1,
                        falla,
                    )
        raise ErrorDeVoz("Azure AI Speech no respondió. Inténtalo de nuevo en unos minutos.")

    def _pedir(self, cliente: httpx.Client, cuerpo: bytes, cabeceras: dict) -> bytes:
        """Una llamada. Devuelve el MP3, lanza ``_FallaPasajera`` o ``ErrorDeVoz``."""
        try:
            with cliente.stream("POST", self.url, content=cuerpo, headers=cabeceras) as respuesta:
                estado = respuesta.status_code
                if estado in ESTADOS_REINTENTABLES:
                    raise _FallaPasajera(f"estado {estado}")
                if estado in (401, 403):
                    raise ErrorDeVoz("Azure AI Speech rechazó la llave o la región configurada.")
                if estado != 200:
                    registro.warning("Azure AI Speech respondió el estado %s.", estado)
                    raise ErrorDeVoz("Azure AI Speech no pudo generar el audio.")
                return self._leer_audio(respuesta)
        except httpx.TimeoutException:
            raise _FallaPasajera("tiempo de espera agotado") from None
        except httpx.TransportError:
            # El mensaje de httpx puede traer detalles de la red; no se repite.
            raise _FallaPasajera("error de conexión") from None

    @staticmethod
    def _leer_audio(respuesta: httpx.Response) -> bytes:
        tipo = respuesta.headers.get("content-type", "").split(";")[0].strip().lower()
        if tipo != TIPO_MP3:
            registro.warning("Azure AI Speech respondió un tipo inesperado: %s", tipo[:40])
            raise ErrorDeVoz("Azure AI Speech respondió algo que no es audio.")

        declarado = respuesta.headers.get("content-length", "")
        if declarado.isdigit() and int(declarado) > BYTES_MAXIMOS:
            raise ErrorDeVoz("El audio que respondió Azure AI Speech es demasiado grande.")

        partes, total = [], 0
        for parte in respuesta.iter_bytes():
            total += len(parte)
            if total > BYTES_MAXIMOS:
                raise ErrorDeVoz("El audio que respondió Azure AI Speech es demasiado grande.")
            partes.append(parte)
        contenido = b"".join(partes)
        if not _parece_mp3(contenido):
            raise ErrorDeVoz("Azure AI Speech respondió algo que no es audio.")
        return contenido
