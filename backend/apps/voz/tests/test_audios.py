"""Proveedor de prueba, generación de audios, almacenamiento privado y muestras."""

import pytest
from django.core.files.storage import storages

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.core.almacenamiento import almacenamiento_privado
from apps.evaluaciones.tests.fabricas import (
    crear_admin,
    crear_alumno,
    crear_docente,
    crear_evaluacion,
    crear_pregunta,
    sesion_de,
)
from apps.voz.models import AudioMuestra, AudioPregunta
from apps.voz.proveedores import (
    BYTES_POR_CUADRO,
    CABECERA_CUADRO,
    ErrorDeVoz,
    ProveedorPrueba,
    ProveedorVoz,
)
from apps.voz.servicios import (
    TEXTO_MUESTRA,
    audio_de_pregunta,
    hash_de_contenido,
    leer_audio,
    muestra_de_voz,
    nombre_de_voz,
)

VOZ = "es-CL-CatalinaNeural"
OTRA_VOZ = "es-CL-LorenzoNeural"


class ProveedorContado(ProveedorVoz):
    """Proveedor de prueba que anota cada llamada."""

    def __init__(self):
        self.llamadas: list[tuple[str, str]] = []

    def sintetizar(self, texto, voz):
        self.llamadas.append((texto, voz))
        return ProveedorPrueba().sintetizar(texto, voz)


class ProveedorQueFalla(ProveedorVoz):
    def sintetizar(self, texto, voz):
        raise ErrorDeVoz("Azure AI Speech no respondió.")


# --- Proveedor de prueba ---------------------------------------------------------------


def test_el_proveedor_de_prueba_entrega_un_mp3_de_cuadros_validos():
    audio = ProveedorPrueba().sintetizar("Hola, ¿cómo estás?", VOZ)
    assert len(audio) % BYTES_POR_CUADRO == 0
    cuadros = [audio[i : i + BYTES_POR_CUADRO] for i in range(0, len(audio), BYTES_POR_CUADRO)]
    assert all(cuadro.startswith(CABECERA_CUADRO) for cuadro in cuadros)


def test_el_audio_de_prueba_dura_segun_el_texto_entre_1_y_30_segundos():
    corto = ProveedorPrueba().sintetizar("Sí", VOZ)
    largo = ProveedorPrueba().sintetizar("palabra " * 50, VOZ)
    enorme = ProveedorPrueba().sintetizar("palabra " * 1000, VOZ)
    # Cada cuadro dura 24 ms.
    assert len(corto) // BYTES_POR_CUADRO == round(1000 / 24)
    assert len(corto) < len(largo) < len(enorme)
    assert len(enorme) // BYTES_POR_CUADRO == round(30_000 / 24)


def test_el_audio_de_prueba_no_lleva_el_texto():
    texto = "Enunciado secreto"
    assert texto.encode() not in ProveedorPrueba().sintetizar(texto, VOZ)


def test_el_proveedor_de_prueba_tambien_valida_la_voz_y_el_texto():
    with pytest.raises(ErrorDeVoz):
        ProveedorPrueba().sintetizar("Hola", "en-US-JennyNeural")
    with pytest.raises(ErrorDeVoz):
        ProveedorPrueba().sintetizar("   ", VOZ)


def test_nombre_de_voz():
    assert nombre_de_voz("es-CL-CatalinaNeural") == "Catalina"
    assert nombre_de_voz("es-CL-LorenzoNeural") == "Lorenzo"
    assert nombre_de_voz("otra") == "otra"


# --- Audios de preguntas ---------------------------------------------------------------------


@pytest.mark.django_db
def test_el_audio_se_genera_y_se_guarda_en_el_almacenamiento_privado():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    proveedor = ProveedorContado()
    audio = audio_de_pregunta(pregunta, VOZ, proveedor)
    assert proveedor.llamadas == [(pregunta.texto, VOZ)]
    assert audio.hash_contenido == hash_de_contenido(VOZ, pregunta.texto)
    assert audio.bytes == len(leer_audio(audio)) > 0
    assert audio.archivo.storage is storages["privado"]


@pytest.mark.django_db
def test_el_nombre_del_archivo_es_aleatorio_y_no_revela_nada():
    evaluacion = crear_evaluacion()
    pregunta = crear_pregunta(evaluacion, orden=1)
    audio = audio_de_pregunta(pregunta, VOZ, ProveedorContado())
    nombre = audio.archivo.name
    assert nombre.startswith("audios/") and nombre.endswith(".mp3")
    for dato in (str(pregunta.id), pregunta.id.hex, str(evaluacion.id), VOZ, "Catalina"):
        assert dato not in nombre


@pytest.mark.django_db
def test_los_archivos_privados_no_tienen_url():
    audio = audio_de_pregunta(crear_pregunta(crear_evaluacion(), orden=1), VOZ)
    with pytest.raises(NotImplementedError):
        audio.archivo.url  # noqa: B018
    with pytest.raises(NotImplementedError):
        almacenamiento_privado().url("audios/x.mp3")


@pytest.mark.django_db
def test_un_audio_con_la_misma_voz_y_texto_no_se_vuelve_a_pedir():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    proveedor = ProveedorContado()
    primero = audio_de_pregunta(pregunta, VOZ, proveedor)
    segundo = audio_de_pregunta(pregunta, VOZ, proveedor)
    assert primero.pk == segundo.pk
    assert len(proveedor.llamadas) == 1


@pytest.mark.django_db
def test_cada_voz_tiene_su_propio_audio():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    proveedor = ProveedorContado()
    audio_de_pregunta(pregunta, VOZ, proveedor)
    audio_de_pregunta(pregunta, OTRA_VOZ, proveedor)
    assert AudioPregunta.objects.filter(pregunta=pregunta).count() == 2
    assert [voz for _, voz in proveedor.llamadas] == [VOZ, OTRA_VOZ]


@pytest.mark.django_db
def test_si_cambia_el_texto_el_audio_se_regenera():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    proveedor = ProveedorContado()
    antes = audio_de_pregunta(pregunta, VOZ, proveedor)
    pregunta.texto = "Texto corregido"
    pregunta.save()
    despues = audio_de_pregunta(pregunta, VOZ, proveedor)
    assert despues.pk == antes.pk
    assert despues.hash_contenido == hash_de_contenido(VOZ, "Texto corregido")
    assert len(proveedor.llamadas) == 2


@pytest.mark.django_db
def test_otra_pregunta_con_el_mismo_texto_reutiliza_el_archivo():
    """Una nueva versión de la evaluación no vuelve a pagar los mismos audios."""
    original = crear_pregunta(crear_evaluacion(), orden=1, texto="La misma pregunta")
    copia = crear_pregunta(crear_evaluacion(), orden=1, texto="La misma pregunta")
    proveedor = ProveedorContado()
    primero = audio_de_pregunta(original, VOZ, proveedor)
    segundo = audio_de_pregunta(copia, VOZ, proveedor)
    assert len(proveedor.llamadas) == 1
    assert segundo.archivo.name == primero.archivo.name
    assert segundo.bytes == primero.bytes


@pytest.mark.django_db
def test_una_voz_no_disponible_no_genera_nada():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    with pytest.raises(ErrorDeVoz):
        audio_de_pregunta(pregunta, "en-US-JennyNeural", ProveedorContado())
    assert not AudioPregunta.objects.exists()


@pytest.mark.django_db
def test_si_el_proveedor_falla_no_queda_un_audio_a_medias():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    with pytest.raises(ErrorDeVoz):
        audio_de_pregunta(pregunta, VOZ, ProveedorQueFalla())
    assert not AudioPregunta.objects.exists()


# --- Muestras -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_la_muestra_se_genera_una_vez_con_un_texto_fijo():
    proveedor = ProveedorContado()
    primera = muestra_de_voz(VOZ, proveedor)
    segunda = muestra_de_voz(VOZ, proveedor)
    assert primera.pk == segunda.pk
    assert proveedor.llamadas == [(TEXTO_MUESTRA, VOZ)]
    assert AudioMuestra.objects.count() == 1


@pytest.mark.django_db
def test_no_hay_muestra_de_una_voz_no_disponible():
    with pytest.raises(ErrorDeVoz):
        muestra_de_voz("en-US-JennyNeural", ProveedorContado())


@pytest.mark.django_db
def test_el_comando_genera_las_muestras_de_todas_las_voces(capsys):
    from django.core.management import call_command

    call_command("generar_muestras")
    salida = capsys.readouterr().out
    assert "Proveedor de voz: prueba" in salida
    assert VOZ in salida and OTRA_VOZ in salida
    assert set(AudioMuestra.objects.values_list("voz", flat=True)) == {VOZ, OTRA_VOZ}


# --- Endpoints de voces ---------------------------------------------------------------------


@pytest.mark.django_db
def test_el_alumno_ve_las_voces_disponibles():
    alumno = crear_alumno(voz_preferida=OTRA_VOZ)
    respuesta = sesion_de(alumno).get("/api/alumno/voces")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "voces": [
            {"id": VOZ, "nombre": "Catalina", "muestra_url": f"/api/alumno/voces/{VOZ}/muestra"},
            {
                "id": OTRA_VOZ,
                "nombre": "Lorenzo",
                "muestra_url": f"/api/alumno/voces/{OTRA_VOZ}/muestra",
            },
        ],
        "voz_preferida": OTRA_VOZ,
    }


@pytest.mark.django_db
def test_una_voz_preferida_que_ya_no_existe_no_se_ofrece():
    alumno = crear_alumno(voz_preferida="es-CL-VozRetiradaNeural")
    assert sesion_de(alumno).get("/api/alumno/voces").json()["voz_preferida"] is None


@pytest.mark.django_db
def test_la_muestra_se_entrega_como_mp3_sin_cache():
    respuesta = sesion_de(crear_alumno()).get(f"/api/alumno/voces/{VOZ}/muestra")
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "audio/mpeg"
    assert respuesta["Cache-Control"] == "no-store"
    assert respuesta["X-Content-Type-Options"] == "nosniff"
    assert respuesta.content.startswith(CABECERA_CUADRO)
    assert int(respuesta["Content-Length"]) == len(respuesta.content)


@pytest.mark.django_db
def test_la_muestra_de_una_voz_desconocida_no_existe():
    respuesta = sesion_de(crear_alumno()).get("/api/alumno/voces/en-US-JennyNeural/muestra")
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "voz_no_disponible"
    assert not AudioMuestra.objects.exists()


@pytest.mark.django_db
def test_si_azure_falla_la_muestra_responde_503_sin_detalles(monkeypatch):
    monkeypatch.setattr("apps.voz.servicios.obtener_proveedor", ProveedorQueFalla)
    respuesta = sesion_de(crear_alumno()).get(f"/api/alumno/voces/{VOZ}/muestra")
    assert respuesta.status_code == 503
    assert respuesta.json()["codigo"] == "muestra_no_disponible"
    assert "Azure" not in respuesta.json()["mensaje"]


@pytest.mark.django_db
@pytest.mark.parametrize("ruta", ["/api/alumno/voces", f"/api/alumno/voces/{VOZ}/muestra"])
def test_sin_sesion_no_hay_voces(ruta):
    from rest_framework.test import APIClient

    assert APIClient().get(ruta).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("crear", [crear_docente, crear_admin])
def test_el_personal_no_usa_los_endpoints_del_alumno(crear):
    usuario = crear()
    navegador = sesion_de(usuario)
    for _ in range(3):
        respuesta = navegador.get("/api/alumno/voces")
        assert respuesta.status_code == 403
    # El rechazo queda en la bitácora una sola vez por minuto.
    registros = RegistroAuditoria.objects.filter(accion=Accion.ACCESO_DENEGADO, actor=usuario)
    assert registros.count() == 1
    assert registros.get().detalle == {"motivo": "rol_no_permitido", "ruta": "/api/alumno/voces"}
