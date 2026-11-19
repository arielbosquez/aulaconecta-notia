"""Proveedor de Azure AI Speech: SSML escapado y respuestas inválidas (RS-12).

Ninguna prueba sale a la red: ``httpx.MockTransport`` hace de Azure y
responde lo que cada caso necesita, incluidas las respuestas malas.
"""

import logging
import xml.etree.ElementTree as ET  # noqa: S405 (solo lee el SSML que arma el propio código)

import httpx
import pytest
from django.test import override_settings

from apps.voz.azure import (
    BYTES_MAXIMOS,
    ESPERAS_ENTRE_INTENTOS,
    FORMATO_SALIDA,
    SEGUNDOS_DE_ESPERA,
    ProveedorAzure,
    armar_ssml,
)
from apps.voz.proveedores import ErrorDeVoz, ProveedorPrueba, mp3_de_silencio, obtener_proveedor

VOZ = "es-CL-CatalinaNeural"
# Llave ficticia, solo para estas pruebas: se busca en errores y registros.
LLAVE = "llave-ficticia-de-prueba-0123456789abcdef"
MP3 = mp3_de_silencio(1)
SSML = "{http://www.w3.org/2001/10/synthesis}"


class Azure:
    """Hace de Azure: responde en orden la lista de respuestas y anota cada petición."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.peticiones: list[httpx.Request] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion)
        respuesta = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


def _audio(contenido=MP3, tipo="audio/mpeg", estado=200, **cabeceras):
    return httpx.Response(estado, content=contenido, headers={"content-type": tipo, **cabeceras})


def _proveedor(azure: Azure, esperas: list | None = None) -> ProveedorAzure:
    return ProveedorAzure(
        llave=LLAVE,
        region="brazilsouth",
        transporte=httpx.MockTransport(azure),
        esperar=(esperas.append if esperas is not None else lambda _: None),
    )


# --- SSML ---------------------------------------------------------------------------


def _leer(ssml: str) -> ET.Element:
    """Lee el SSML que armó ``armar_ssml`` para revisar su estructura.

    No es XML externo: lo genera el propio código bajo prueba, y justamente
    se comprueba que no trae entidades, DOCTYPE ni etiquetas inyectadas.
    """
    return ET.fromstring(ssml)  # noqa: S314  # nosec B314


def test_el_ssml_tiene_la_voz_y_el_idioma():
    raiz = _leer(armar_ssml("¿Cuánto es 2 + 2?", VOZ))
    assert raiz.tag == f"{SSML}speak"
    assert raiz.get("{http://www.w3.org/XML/1998/namespace}lang") == "es-CL"
    [voz] = list(raiz)
    assert voz.tag == f"{SSML}voice"
    assert voz.get("name") == VOZ
    assert voz.text == "¿Cuánto es 2 + 2?"


@pytest.mark.parametrize(
    "texto",
    [
        'Si a < b & b > c, ¿qué dice "Juan"?',
        "</voice><voice name=\"es-CL-LorenzoNeural\">Otra voz</voice><voice name='x'>",
        '<break time="10s"/><prosody rate="x-fast">rápido</prosody>',
        "&lt; ya escapado &amp; doble",
        "<!DOCTYPE x [<!ENTITY a 'b'>]>&a;",
    ],
)
def test_el_texto_se_escapa_y_no_puede_agregar_etiquetas(texto):
    ssml = armar_ssml(texto, VOZ)
    raiz = _leer(ssml)
    [voz] = list(raiz)
    # Una sola voz, sin hijos: todo lo que escribió el docente quedó como texto.
    assert voz.get("name") == VOZ
    assert list(voz) == []
    assert voz.text == texto
    assert "<break" not in ssml and "<prosody" not in ssml and "<!DOCTYPE" not in ssml


def test_los_caracteres_especiales_quedan_como_entidades():
    ssml = armar_ssml('a < b & "c" \'d\'', VOZ)
    assert "a &lt; b &amp; &quot;c&quot; &apos;d&apos;" in ssml


def test_los_caracteres_de_control_se_descartan():
    raiz = _leer(armar_ssml("Hola\x00\x07 mundo\x1f", VOZ))
    assert list(raiz)[0].text == "Hola   mundo"


def test_una_voz_fuera_de_la_lista_no_se_usa():
    with pytest.raises(ErrorDeVoz):
        armar_ssml("Hola", 'es-CL-CatalinaNeural" xml:lang="en-US')
    with pytest.raises(ErrorDeVoz):
        armar_ssml("Hola", "en-US-JennyNeural")


@override_settings(VOCES_DISPONIBLES=["voz rara"])
def test_una_voz_configurada_con_forma_extrana_tampoco_entra_al_ssml():
    with pytest.raises(ErrorDeVoz):
        armar_ssml("Hola", "voz rara")


def test_sin_texto_no_hay_ssml():
    with pytest.raises(ErrorDeVoz):
        armar_ssml(" \x00 ", VOZ)


# --- La llamada ------------------------------------------------------------------------


def test_la_peticion_lleva_la_llave_en_la_cabecera_y_el_formato_mp3():
    azure = Azure(_audio())
    assert _proveedor(azure).sintetizar("Hola", VOZ) == MP3
    [peticion] = azure.peticiones
    assert peticion.method == "POST"
    assert str(peticion.url) == "https://brazilsouth.tts.speech.microsoft.com/cognitiveservices/v1"
    assert peticion.headers["Ocp-Apim-Subscription-Key"] == LLAVE
    assert peticion.headers["Content-Type"] == "application/ssml+xml"
    assert peticion.headers["X-Microsoft-OutputFormat"] == FORMATO_SALIDA
    assert peticion.headers["User-Agent"] == "NotIA"
    # La llave nunca va en la URL ni en el cuerpo.
    assert LLAVE not in str(peticion.url)
    assert LLAVE.encode() not in peticion.content
    assert _leer(peticion.content.decode()).tag == f"{SSML}speak"


def test_la_peticion_tiene_tiempo_de_espera_de_10_segundos():
    azure = Azure(_audio())
    _proveedor(azure).sintetizar("Hola", VOZ)
    tiempos = azure.peticiones[0].extensions["timeout"]
    assert SEGUNDOS_DE_ESPERA == 10
    assert set(tiempos.values()) == {10.0}


def test_una_respuesta_con_etiqueta_id3_tambien_es_mp3():
    contenido = b"ID3\x04\x00" + bytes(20) + MP3
    assert _proveedor(Azure(_audio(contenido))).sintetizar("Hola", VOZ) == contenido


@pytest.mark.parametrize("estado", [500, 502, 503, 504, 429, 408])
def test_una_falla_pasajera_se_reintenta_con_espera_creciente(estado):
    azure = Azure(_audio(b"", "text/plain", estado), _audio(b"", "text/plain", estado), _audio())
    esperas: list[float] = []
    assert _proveedor(azure, esperas).sintetizar("Hola", VOZ) == MP3
    assert len(azure.peticiones) == 3
    assert esperas == list(ESPERAS_ENTRE_INTENTOS)
    assert esperas[0] < esperas[1]


def test_despues_de_2_reintentos_se_rinde():
    azure = Azure(_audio(b"", "text/plain", 503))
    with pytest.raises(ErrorDeVoz, match="no respondió"):
        _proveedor(azure).sintetizar("Hola", VOZ)
    assert len(azure.peticiones) == 3


def test_un_tiempo_de_espera_agotado_se_reintenta():
    azure = Azure(httpx.ReadTimeout("lento"), _audio())
    assert _proveedor(azure).sintetizar("Hola", VOZ) == MP3
    assert len(azure.peticiones) == 2


def test_un_error_de_conexion_se_reintenta_y_luego_falla():
    azure = Azure(httpx.ConnectError("sin red"))
    with pytest.raises(ErrorDeVoz):
        _proveedor(azure).sintetizar("Hola", VOZ)
    assert len(azure.peticiones) == 3


@pytest.mark.parametrize("estado", [400, 401, 403, 404])
def test_un_rechazo_definitivo_no_se_reintenta(estado):
    azure = Azure(_audio(b"{}", "application/json", estado))
    with pytest.raises(ErrorDeVoz):
        _proveedor(azure).sintetizar("Hola", VOZ)
    assert len(azure.peticiones) == 1


@pytest.mark.parametrize(
    ("contenido", "tipo"),
    [
        (b"<html>error</html>", "text/html"),
        (MP3, "application/octet-stream"),
        (MP3, ""),
        (b"", "audio/mpeg"),
        (b"no es un mp3", "audio/mpeg"),
        (b"RIFF\x00\x00\x00\x00WAVE", "audio/mpeg"),
    ],
)
def test_una_respuesta_que_no_es_mp3_se_rechaza(contenido, tipo):
    azure = Azure(_audio(contenido, tipo))
    with pytest.raises(ErrorDeVoz, match="no es audio"):
        _proveedor(azure).sintetizar("Hola", VOZ)
    assert len(azure.peticiones) == 1


def test_un_audio_que_declara_un_tamano_enorme_se_rechaza():
    azure = Azure(_audio(MP3, **{"content-length": str(BYTES_MAXIMOS + 1)}))
    with pytest.raises(ErrorDeVoz, match="demasiado grande"):
        _proveedor(azure).sintetizar("Hola", VOZ)


def test_un_audio_enorme_sin_tamano_declarado_se_corta_al_leerlo():
    def partes():
        yield MP3
        for _ in range(BYTES_MAXIMOS // 65536 + 2):
            yield bytes(65536)

    azure = Azure(httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=partes()))
    with pytest.raises(ErrorDeVoz, match="demasiado grande"):
        _proveedor(azure).sintetizar("Hola", VOZ)


def test_no_sigue_redirecciones():
    azure = Azure(httpx.Response(302, headers={"location": "https://otro.example/"}))
    with pytest.raises(ErrorDeVoz):
        _proveedor(azure).sintetizar("Hola", VOZ)
    assert len(azure.peticiones) == 1


# --- La llave ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "respuesta",
    [
        _audio(b"", "text/plain", 401),
        _audio(b"", "text/plain", 503),
        _audio(b"x", "text/html"),
        httpx.ConnectError(f"fallo con {LLAVE}"),
    ],
)
def test_la_llave_nunca_aparece_en_errores_ni_registros(respuesta, caplog):
    caplog.set_level(logging.DEBUG)
    proveedor = _proveedor(Azure(respuesta))
    with pytest.raises(ErrorDeVoz) as error:
        proveedor.sintetizar("Hola", VOZ)
    assert LLAVE not in str(error.value)
    assert error.value.__cause__ is None or LLAVE not in str(error.value.__cause__)
    assert LLAVE not in caplog.text
    assert LLAVE not in repr(proveedor)


def test_el_texto_de_la_pregunta_no_queda_en_los_registros(caplog):
    caplog.set_level(logging.DEBUG)
    texto = "Enunciado que solo se escucha"
    with pytest.raises(ErrorDeVoz):
        _proveedor(Azure(_audio(b"", "text/plain", 503))).sintetizar(texto, VOZ)
    assert texto not in caplog.text


@pytest.mark.parametrize("region", ["", "brazil south", "evil.com/x", "a" * 41, "BRAZILSOUTH#"])
def test_una_region_que_podria_cambiar_la_url_se_rechaza(region):
    with pytest.raises(ErrorDeVoz):
        ProveedorAzure(llave=LLAVE, region=region)


def test_sin_llave_no_se_crea_el_proveedor():
    with pytest.raises(ErrorDeVoz):
        ProveedorAzure(llave="", region="brazilsouth")


# --- Elección del proveedor ------------------------------------------------------------------


def test_las_pruebas_usan_siempre_el_proveedor_sin_red(settings):
    assert settings.PROVEEDOR_VOZ == "prueba"
    assert settings.AZURE_SPEECH_KEY == ""
    assert isinstance(obtener_proveedor(), ProveedorPrueba)


def test_con_azure_configurado_se_usa_el_proveedor_de_azure(settings):
    settings.PROVEEDOR_VOZ = "azure"
    settings.AZURE_SPEECH_KEY = LLAVE
    settings.AZURE_SPEECH_REGION = "brazilsouth"
    proveedor = obtener_proveedor()
    assert isinstance(proveedor, ProveedorAzure)
    assert proveedor.region == "brazilsouth"
