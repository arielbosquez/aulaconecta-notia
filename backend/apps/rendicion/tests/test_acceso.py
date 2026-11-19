"""Autorización en los endpoints del alumno (sección 10, RS-07).

- Horizontal: un alumno contra el intento, las respuestas y las pruebas de
  otro. Responde 404, como si no existieran, no cambia nada y queda en la
  bitácora (una vez por minuto).
- Vertical: docentes y administradores no usan los endpoints del alumno.
- El audio y la imagen se entregan solo para la pregunta en curso.
"""

from datetime import UTC, datetime

import pytest
import time_machine
from django.core.cache import cache
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.core.almacenamiento import almacenamiento_privado
from apps.cuentas.limites import LimitePorUsuario
from apps.evaluaciones.models import Modalidad
from apps.evaluaciones.tests.fabricas import (
    asignar,
    crear_admin,
    crear_alumno,
    crear_docente,
    sesion_de,
)
from apps.rendicion.models import EstadoRespuesta, Intento, Respuesta
from apps.voz.models import AudioPregunta
from apps.voz.proveedores import ProveedorVoz, mp3_de_silencio
from apps.voz.servicios import audio_de_pregunta

from .ayudantes import (
    OTRA_VOZ,
    VOZ,
    actual,
    cambiar_voz,
    iniciado,
    iniciar,
    pasar,
    preparar,
    primera_alternativa,
    responder,
    responder_primera,
)

pytestmark = pytest.mark.django_db

UUID_INEXISTENTE = "6b0f3f8e-0000-4000-8000-000000000000"


class ProveedorPorVoz(ProveedorVoz):
    """Un audio distinto por voz (1 o 2 segundos), para saber cuál se entregó."""

    def sintetizar(self, texto, voz):
        return mp3_de_silencio(1 if voz == VOZ else 2)


def _con_audios(evaluacion):
    for pregunta in evaluacion.preguntas.all():
        for voz in (VOZ, OTRA_VOZ):
            audio_de_pregunta(pregunta, voz, ProveedorPorVoz())


@pytest.fixture
def rendicion_de_a():
    """El alumno A con un intento en curso y su primera pregunta presentada."""
    evaluacion, alumno_a, navegador_a = preparar(preguntas=3)
    _con_audios(evaluacion)
    intento_id = iniciado(navegador_a, evaluacion)
    cuerpo = actual(navegador_a, intento_id).json()
    return evaluacion, alumno_a, navegador_a, intento_id, cuerpo


def _denegados(usuario):
    return RegistroAuditoria.objects.filter(accion=Accion.ACCESO_DENEGADO, actor=usuario)


# --- Horizontal: alumno contra alumno ---------------------------------------------------------


def test_otro_alumno_no_puede_tocar_el_intento_de_a(rendicion_de_a):
    evaluacion, _, _, intento_id, cuerpo = rendicion_de_a
    alumno_b = crear_alumno()
    asignar(evaluacion, alumno_b)
    navegador_b = sesion_de(alumno_b)
    ref = cuerpo["pregunta"]["ref"]

    intentos = [
        actual(navegador_b, intento_id),
        responder_primera(navegador_b, intento_id, cuerpo),
        pasar(navegador_b, intento_id, ref),
        cambiar_voz(navegador_b, intento_id, OTRA_VOZ),
        navegador_b.get(f"/api/alumno/respuestas/{ref}/audio"),
        navegador_b.get(f"/api/alumno/respuestas/{ref}/imagen"),
        navegador_b.enviar(f"/api/alumno/respuestas/{ref}/repeticion"),
    ]
    assert [r.status_code for r in intentos] == [404] * len(intentos)
    # El mismo cuerpo que una ruta inexistente: no se confirma que el intento exista.
    assert {r.json()["codigo"] for r in intentos} == {"no_encontrado"}

    respuesta = Respuesta.objects.get(pk=ref)
    assert respuesta.estado == EstadoRespuesta.EN_CURSO
    assert respuesta.repeticiones_audio == 0
    assert Intento.objects.get(pk=intento_id).voz == VOZ


def test_el_acceso_ajeno_queda_en_la_bitacora_una_vez_por_minuto(rendicion_de_a):
    _, _, _, intento_id, cuerpo = rendicion_de_a
    alumno_b = crear_alumno()
    navegador_b = sesion_de(alumno_b)
    for _ in range(5):
        actual(navegador_b, intento_id)
    for _ in range(3):
        navegador_b.get(f"/api/alumno/respuestas/{cuerpo['pregunta']['ref']}/audio")

    registros = _denegados(alumno_b)
    assert {r.detalle["objeto_tipo"] for r in registros} == {
        "rendicion.Intento",
        "rendicion.Respuesta",
    }
    assert registros.count() == 2
    for registro in registros:
        assert registro.detalle["motivo"] == "objeto_ajeno"
        assert registro.rol_actor == "ALUMNO"


def test_un_identificador_inexistente_responde_igual_y_no_se_registra():
    alumno = crear_alumno()
    navegador = sesion_de(alumno)
    assert actual(navegador, UUID_INEXISTENTE).status_code == 404
    assert navegador.get(f"/api/alumno/respuestas/{UUID_INEXISTENTE}/audio").status_code == 404
    assert not _denegados(alumno).exists()


def test_la_ref_de_otro_alumno_no_sirve_en_el_intento_propio(rendicion_de_a):
    evaluacion, _, _, _, cuerpo_a = rendicion_de_a
    alumno_b = crear_alumno()
    asignar(evaluacion, alumno_b)
    navegador_b = sesion_de(alumno_b)
    intento_b = iniciado(navegador_b, evaluacion)
    actual(navegador_b, intento_b)

    ajena = cuerpo_a["pregunta"]["ref"]
    respuesta = responder(navegador_b, intento_b, ajena, primera_alternativa(cuerpo_a))
    assert respuesta.status_code == 409
    assert pasar(navegador_b, intento_b, ajena).status_code == 409
    assert Respuesta.objects.get(pk=ajena).estado == EstadoRespuesta.EN_CURSO


def test_no_se_inicia_una_prueba_asignada_a_otro(rendicion_de_a):
    evaluacion = rendicion_de_a[0]
    alumno_b = crear_alumno()
    respuesta = iniciar(sesion_de(alumno_b), evaluacion)
    assert respuesta.status_code == 404
    assert not Intento.objects.filter(alumno=alumno_b).exists()
    assert _denegados(alumno_b).get().detalle["objeto_tipo"] == "evaluaciones.Evaluacion"


def test_la_lista_de_pruebas_solo_muestra_las_propias(rendicion_de_a):
    alumno_b = crear_alumno()
    assert sesion_de(alumno_b).get("/api/alumno/evaluaciones").json() == {"resultados": []}


# --- Vertical: personal contra endpoints del alumno -----------------------------------------------


def _rutas_del_alumno(evaluacion, intento_id, ref):
    return [
        ("get", "/api/alumno/evaluaciones"),
        ("get", "/api/alumno/voces"),
        ("get", f"/api/alumno/voces/{VOZ}/muestra"),
        ("get", "/api/alumno/resultados"),
        ("post", f"/api/alumno/evaluaciones/{evaluacion.id}/iniciar"),
        ("get", f"/api/alumno/intentos/{intento_id}/actual"),
        ("post", f"/api/alumno/intentos/{intento_id}/responder"),
        ("post", f"/api/alumno/intentos/{intento_id}/pasar"),
        ("patch", f"/api/alumno/intentos/{intento_id}/voz"),
        ("post", f"/api/alumno/respuestas/{ref}/repeticion"),
        ("get", f"/api/alumno/respuestas/{ref}/audio"),
        ("get", f"/api/alumno/respuestas/{ref}/imagen"),
    ]


@pytest.mark.parametrize("crear", [crear_docente, crear_admin], ids=["docente", "admin"])
def test_el_personal_recibe_403_en_todos_los_endpoints_del_alumno(rendicion_de_a, crear):
    evaluacion, _, _, intento_id, cuerpo = rendicion_de_a
    usuario = crear()
    navegador = sesion_de(usuario)
    csrf = {"HTTP_X_CSRFTOKEN": navegador.cookies["csrftoken"].value}
    for metodo, ruta in _rutas_del_alumno(evaluacion, intento_id, cuerpo["pregunta"]["ref"]):
        respuesta = getattr(navegador, metodo)(ruta, {}, format="json", **csrf)
        assert respuesta.status_code == 403, ruta
    assert Respuesta.objects.get(pk=cuerpo["pregunta"]["ref"]).estado == EstadoRespuesta.EN_CURSO
    # Muchos intentos, un solo registro por minuto.
    assert _denegados(usuario).count() == 1


def test_sin_sesion_todos_los_endpoints_del_alumno_responden_401(rendicion_de_a):
    evaluacion, _, _, intento_id, cuerpo = rendicion_de_a
    cliente = APIClient()
    for metodo, ruta in _rutas_del_alumno(evaluacion, intento_id, cuerpo["pregunta"]["ref"]):
        assert getattr(cliente, metodo)(ruta).status_code == 401, ruta


def test_las_operaciones_del_alumno_exigen_csrf(rendicion_de_a):
    _, _, navegador_a, intento_id, cuerpo = rendicion_de_a
    ruta = f"/api/alumno/intentos/{intento_id}/pasar"
    sin_csrf = navegador_a.enviar(ruta, {"ref": cuerpo["pregunta"]["ref"]}, con_csrf=False)
    assert sin_csrf.status_code == 403
    assert sin_csrf.json()["codigo"] == "csrf_invalido"
    assert Respuesta.objects.get(pk=cuerpo["pregunta"]["ref"]).estado == EstadoRespuesta.EN_CURSO


def test_el_limite_general_por_usuario_responde_429(rendicion_de_a, monkeypatch, settings):
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["usuario"] == "300/min"
    _, _, navegador_a, intento_id, _ = rendicion_de_a
    # 3 por minuto en vez de 300, para no hacer 300 peticiones.
    monkeypatch.setattr(LimitePorUsuario, "THROTTLE_RATES", {"usuario": "3/min"})
    cache.clear()
    estados = [actual(navegador_a, intento_id).status_code for _ in range(5)]
    assert estados[:3] == [200, 200, 200]
    assert estados[3:] == [429, 429]


# --- Audio e imagen: solo la pregunta en curso ----------------------------------------


def test_el_audio_de_la_pregunta_en_curso_se_entrega_sin_cache(rendicion_de_a):
    _, _, navegador_a, _, cuerpo = rendicion_de_a
    respuesta = navegador_a.get(cuerpo["pregunta"]["audio_url"])
    assert respuesta.status_code == 200
    assert respuesta["Content-Type"] == "audio/mpeg"
    assert respuesta["Cache-Control"] == "no-store"
    assert respuesta["X-Content-Type-Options"] == "nosniff"
    assert respuesta.content == mp3_de_silencio(1)


def test_el_audio_sigue_la_voz_elegida(rendicion_de_a):
    _, _, navegador_a, intento_id, cuerpo = rendicion_de_a
    cambiar_voz(navegador_a, intento_id, OTRA_VOZ)
    assert navegador_a.get(cuerpo["pregunta"]["audio_url"]).content == mp3_de_silencio(2)


def test_el_audio_de_una_pregunta_que_no_esta_en_curso_no_se_entrega(rendicion_de_a):
    _, _, navegador_a, intento_id, cuerpo = rendicion_de_a
    intento = Intento.objects.get(pk=intento_id)
    futura = intento.respuestas.get(orden_presentacion=3)
    assert navegador_a.get(f"/api/alumno/respuestas/{futura.id}/audio").status_code == 409
    # Ni la que se acaba de pasar.
    pasar(navegador_a, intento_id, cuerpo["pregunta"]["ref"])
    assert navegador_a.get(cuerpo["pregunta"]["audio_url"]).status_code == 409


def test_el_audio_no_se_entrega_cuando_se_acaba_el_tiempo():
    with time_machine.travel(datetime(2026, 11, 20, 13, 0, tzinfo=UTC), tick=False) as reloj:
        evaluacion, _, navegador = preparar(preguntas=2, tiempo=30)
        _con_audios(evaluacion)
        intento_id = iniciado(navegador, evaluacion)
        cuerpo = actual(navegador, intento_id).json()
        reloj.shift(29)
        assert navegador.get(cuerpo["pregunta"]["audio_url"]).status_code == 200
        reloj.shift(1)
        vencido = navegador.get(cuerpo["pregunta"]["audio_url"])
        assert vencido.status_code == 409
        assert vencido.json()["codigo"] == "tiempo_agotado"


def test_en_modalidad_normal_no_hay_audio():
    evaluacion, _, navegador = preparar(modalidad=Modalidad.NORMAL)
    _con_audios(evaluacion)
    intento_id = iniciado(navegador, evaluacion, voz=None)
    ref = actual(navegador, intento_id).json()["pregunta"]["ref"]
    assert navegador.get(f"/api/alumno/respuestas/{ref}/audio").status_code == 404


def test_si_falta_el_audio_se_avisa_sin_generarlo(rendicion_de_a, monkeypatch):
    evaluacion, _, navegador_a, intento_id, cuerpo = rendicion_de_a
    AudioPregunta.objects.filter(pregunta__evaluacion=evaluacion).delete()
    monkeypatch.setattr(
        "apps.voz.servicios.obtener_proveedor",
        lambda: pytest.fail("Durante la prueba no se llama al proveedor de voz"),
    )
    respuesta = navegador_a.get(cuerpo["pregunta"]["audio_url"])
    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "audio_no_disponible"


def test_la_imagen_se_entrega_solo_mientras_la_pregunta_esta_en_curso():
    evaluacion, _, navegador = preparar(preguntas=2)
    ruta = almacenamiento_privado().save("imagenes/x.webp", ContentFile(b"RIFF....WEBPVP8 "))
    evaluacion.preguntas.filter(orden=1).update(imagen=ruta)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    assert cuerpo["pregunta"]["imagen_url"] is not None

    imagen = navegador.get(cuerpo["pregunta"]["imagen_url"])
    assert imagen.status_code == 200
    assert imagen["Content-Type"] == "image/webp"
    assert imagen["Cache-Control"] == "no-store"
    assert imagen["X-Content-Type-Options"] == "nosniff"

    siguiente = responder_primera(navegador, intento_id, cuerpo).json()
    assert navegador.get(cuerpo["pregunta"]["imagen_url"]).status_code == 409
    # La segunda pregunta no tiene imagen.
    assert siguiente["pregunta"]["imagen_url"] is None
    sin_imagen = f"/api/alumno/respuestas/{siguiente['pregunta']['ref']}/imagen"
    assert navegador.get(sin_imagen).status_code == 404
