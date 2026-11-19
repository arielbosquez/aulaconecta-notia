"""Motor de rendición con tiempo simulado (sección 7, RS-09).

``time-machine`` congela la hora del servidor y la mueve a voluntad: así se
prueba qué pasa a los 20 segundos, al agotarse el tiempo o tras una
desconexión larga sin esperar de verdad. En ninguna prueba el navegador
informa el tiempo: lo decide siempre el servidor.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import time_machine

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.evaluaciones.models import EstadoEvaluacion, Modalidad
from apps.evaluaciones.tests.fabricas import asignar, crear_alumno, crear_evaluacion, sesion_de
from apps.rendicion.models import EstadoIntento, EstadoRespuesta, Intento, Respuesta
from apps.resultados.models import EstadoResultado, Resultado

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

INICIO = datetime(2026, 11, 20, 13, 0, tzinfo=UTC)


@pytest.fixture
def reloj():
    """Hora del servidor congelada; ``reloj.shift(segundos)`` la adelanta."""
    with time_machine.travel(INICIO, tick=False) as viaje:
        yield viaje


def _respuesta(ref) -> Respuesta:
    return Respuesta.objects.get(pk=ref)


# --- Iniciar ------------------------------------------------------------------------------


def test_iniciar_crea_una_respuesta_por_pregunta_con_sus_alternativas(reloj):
    evaluacion, alumno, navegador = preparar(preguntas=4)
    respuesta = iniciar(navegador, evaluacion)
    assert respuesta.status_code == 201
    assert respuesta.json() == {
        "intento": respuesta.json()["intento"],
        "estado": "EN_CURSO",
        "modalidad": "NOTIA",
    }
    intento = Intento.objects.get(pk=respuesta.json()["intento"])
    assert intento.voz == VOZ
    assert intento.iniciado_en == INICIO
    respuestas = list(intento.respuestas.order_by("orden_presentacion"))
    assert [r.orden_presentacion for r in respuestas] == [1, 2, 3, 4]
    assert all(r.estado == EstadoRespuesta.NO_VISTA for r in respuestas)
    for r in respuestas:
        ids = {str(a.id) for a in r.pregunta.alternativas.all()}
        assert sorted(r.orden_alternativas) == sorted(ids)
    alumno.refresh_from_db()
    assert alumno.voz_preferida == VOZ
    registro = RegistroAuditoria.objects.get(accion=Accion.INTENTO_INICIADO)
    assert registro.actor == alumno
    assert registro.objeto_id == str(intento.id)
    assert registro.detalle == {"modalidad": "NOTIA"}


def test_el_orden_de_preguntas_y_alternativas_se_baraja_por_alumno():
    evaluacion = crear_evaluacion(preguntas=8, alternativas=6, publicada=True)
    ordenes_preguntas, ordenes_alternativas = set(), set()
    for _ in range(5):
        alumno = crear_alumno()
        asignar(evaluacion, alumno)
        intento = Intento.objects.get(pk=iniciado(sesion_de(alumno), evaluacion))
        respuestas = intento.respuestas.order_by("orden_presentacion")
        ordenes_preguntas.add(tuple(r.pregunta.orden for r in respuestas))
        ordenes_alternativas.add(tuple(respuestas[0].orden_alternativas))
    # Que 5 alumnos reciban el mismo orden de 8 preguntas tiene probabilidad (1/8!)^4.
    assert len(ordenes_preguntas) > 1
    assert len(ordenes_alternativas) > 1


def test_sin_aleatorizar_se_respeta_el_orden_del_docente():
    evaluacion, _, navegador = preparar(preguntas=5, aleatorizar_alternativas=False)
    intento = Intento.objects.get(pk=iniciado(navegador, evaluacion))
    for respuesta in intento.respuestas.order_by("orden_presentacion"):
        assert respuesta.pregunta.orden == respuesta.orden_presentacion
        esperado = [str(a.id) for a in respuesta.pregunta.alternativas.order_by("orden")]
        assert respuesta.orden_alternativas == esperado


def test_no_se_puede_iniciar_dos_veces(reloj):
    evaluacion, _, navegador = preparar()
    iniciado(navegador, evaluacion)
    respuesta = iniciar(navegador, evaluacion)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "intento_existente"
    assert Intento.objects.count() == 1


def test_antes_del_inicio_de_la_ventana_no_se_puede_iniciar(reloj):
    evaluacion, _, navegador = preparar(inicio=INICIO + timedelta(minutes=5))
    respuesta = iniciar(navegador, evaluacion)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "prueba_no_comenzada"
    assert not Intento.objects.exists()


def test_despues_del_fin_de_la_ventana_no_se_puede_iniciar(reloj):
    evaluacion, _, navegador = preparar(
        inicio=INICIO - timedelta(hours=2), fin=INICIO - timedelta(seconds=1)
    )
    respuesta = iniciar(navegador, evaluacion)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "prueba_terminada"


def test_una_evaluacion_cerrada_no_se_puede_iniciar(reloj):
    evaluacion, _, navegador = preparar()
    evaluacion.estado = EstadoEvaluacion.CERRADA
    evaluacion.save()
    assert iniciar(navegador, evaluacion).json()["codigo"] == "prueba_terminada"


def test_una_evaluacion_en_borrador_no_existe_para_el_alumno(reloj):
    evaluacion, _, navegador = preparar()
    evaluacion.estado = EstadoEvaluacion.BORRADOR
    evaluacion.publicada_en = None
    evaluacion.save()
    assert iniciar(navegador, evaluacion).status_code == 404


def test_sin_asignacion_no_se_puede_iniciar(reloj):
    evaluacion, _, _ = preparar()
    otro = sesion_de(crear_alumno())
    assert iniciar(otro, evaluacion).status_code == 404
    assert not Intento.objects.exists()


def test_en_notia_hay_que_elegir_una_voz_disponible(reloj):
    evaluacion, _, navegador = preparar()
    sin_voz = iniciar(navegador, evaluacion, voz=None)
    assert sin_voz.status_code == 400
    assert "voz" in sin_voz.json()["detalle"]
    otra = iniciar(navegador, evaluacion, voz="en-US-JennyNeural")
    assert otra.status_code == 400
    assert not Intento.objects.exists()


def test_en_modalidad_normal_no_hace_falta_voz(reloj):
    evaluacion, _, navegador = preparar(modalidad=Modalidad.NORMAL)
    intento = Intento.objects.get(pk=iniciado(navegador, evaluacion, voz=None))
    assert intento.modalidad == Modalidad.NORMAL
    assert intento.voz == ""


def test_iniciar_rechaza_campos_desconocidos(reloj):
    evaluacion, _, navegador = preparar()
    respuesta = navegador.enviar(
        f"/api/alumno/evaluaciones/{evaluacion.id}/iniciar", {"voz": VOZ, "ronda": 2}
    )
    assert respuesta.status_code == 400
    assert not Intento.objects.exists()


# --- Responder a tiempo ---------------------------------------------------------------------


def test_la_primera_pregunta_se_presenta_con_su_tiempo_completo(reloj):
    evaluacion, _, navegador = preparar(tiempo=45)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    assert cuerpo["estado"] == "EN_CURSO"
    assert cuerpo["ronda"] == 1
    pregunta = cuerpo["pregunta"]
    assert pregunta["numero"] == 1
    assert pregunta["total"] == 3
    assert pregunta["tiempo_total_ms"] == 45_000
    assert pregunta["restante_ms"] == 45_000
    assert [a["letra"] for a in pregunta["alternativas"]] == ["A", "B", "C", "D"]
    assert _respuesta(pregunta["ref"]).presentada_en == INICIO


def test_el_tiempo_restante_lo_calcula_el_servidor(reloj):
    evaluacion, _, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    actual(navegador, intento_id)
    reloj.shift(12.5)
    assert actual(navegador, intento_id).json()["pregunta"]["restante_ms"] == 47_500


def test_responder_a_tiempo_guarda_la_respuesta_y_presenta_la_siguiente(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()
    reloj.shift(20)
    elegida = primera_alternativa(primera)
    siguiente = responder(navegador, intento_id, primera["pregunta"]["ref"], elegida)
    assert siguiente.status_code == 200
    assert siguiente.json()["pregunta"]["numero"] == 2
    assert siguiente.json()["pregunta"]["restante_ms"] == 60_000

    guardada = _respuesta(primera["pregunta"]["ref"])
    assert guardada.estado == EstadoRespuesta.RESPONDIDA
    assert str(guardada.alternativa_id) == elegida
    assert guardada.segundos_usados == Decimal("20.000")
    assert guardada.respondida_en == INICIO + timedelta(seconds=20)
    assert guardada.presentada_en is None


def test_una_respuesta_dada_no_se_cambia(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()["pregunta"]
    responder(navegador, intento_id, primera["ref"], primera["alternativas"][0]["id"])
    otra = responder(navegador, intento_id, primera["ref"], primera["alternativas"][1]["id"])
    assert otra.status_code == 409
    assert otra.json()["codigo"] == "pregunta_no_disponible"
    assert str(_respuesta(primera["ref"]).alternativa_id) == primera["alternativas"][0]["id"]


def test_no_se_responde_una_pregunta_que_no_esta_en_curso(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    actual(navegador, intento_id)
    intento = Intento.objects.get(pk=intento_id)
    tercera = intento.respuestas.get(orden_presentacion=3)
    respuesta = responder(navegador, intento_id, tercera.id, tercera.orden_alternativas[0])
    assert respuesta.status_code == 409
    assert _respuesta(tercera.id).estado == EstadoRespuesta.NO_VISTA


def test_no_se_responde_con_una_alternativa_de_otra_pregunta(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()["pregunta"]
    de_otra = Intento.objects.get(pk=intento_id).respuestas.get(orden_presentacion=2)
    respuesta = responder(navegador, intento_id, primera["ref"], de_otra.orden_alternativas[0])
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "alternativa_invalida"
    assert _respuesta(primera["ref"]).estado == EstadoRespuesta.EN_CURSO


def test_responder_valida_los_datos(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()["pregunta"]
    ruta = f"/api/alumno/intentos/{intento_id}/responder"
    casos = [
        {},
        {"ref": "no-es-uuid", "alternativa_id": primera["alternativas"][0]["id"]},
        {"ref": primera["ref"]},
        # El navegador no puede informar el tiempo ni nada más.
        {
            "ref": primera["ref"],
            "alternativa_id": primera["alternativas"][0]["id"],
            "restante_ms": 60_000,
        },
    ]
    for datos in casos:
        assert navegador.enviar(ruta, datos).status_code == 400
    assert _respuesta(primera["ref"]).estado == EstadoRespuesta.EN_CURSO


# --- Pasar y volver con el tiempo restante --------------------------------------------------


def test_pasar_deja_la_pregunta_para_la_ronda_2_con_el_tiempo_que_le_quedaba(reloj):
    evaluacion, _, navegador = preparar(preguntas=3, tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()["pregunta"]
    reloj.shift(20)
    segunda = pasar(navegador, intento_id, primera["ref"]).json()
    assert segunda["pregunta"]["numero"] == 2
    pasada = _respuesta(primera["ref"])
    assert pasada.estado == EstadoRespuesta.PASADA
    assert pasada.segundos_usados == Decimal("20.000")

    for _ in range(2):
        reloj.shift(5)
        cuerpo = actual(navegador, intento_id).json()
        responder_primera(navegador, intento_id, cuerpo)

    vuelta = actual(navegador, intento_id).json()
    assert vuelta["ronda"] == 2
    assert vuelta["pregunta"]["ref"] == primera["ref"]
    assert vuelta["pregunta"]["numero"] == 1
    assert vuelta["pregunta"]["restante_ms"] == 40_000
    # El reloj sigue desde lo que le quedaba.
    reloj.shift(15)
    assert actual(navegador, intento_id).json()["pregunta"]["restante_ms"] == 25_000


def test_en_la_ronda_2_pasar_lleva_a_la_siguiente_pasada(reloj):
    evaluacion, _, navegador = preparar(preguntas=3)
    intento_id = iniciado(navegador, evaluacion)
    refs = []
    for _ in range(3):
        cuerpo = actual(navegador, intento_id).json()
        refs.append(cuerpo["pregunta"]["ref"])
        reloj.shift(5)
        pasar(navegador, intento_id, cuerpo["pregunta"]["ref"])
    # Ronda 2: 1, luego 2, luego 3 y de vuelta a la 1.
    vistas = []
    for _ in range(4):
        cuerpo = actual(navegador, intento_id).json()
        assert cuerpo["ronda"] == 2
        vistas.append(cuerpo["pregunta"]["ref"])
        reloj.shift(5)
        pasar(navegador, intento_id, cuerpo["pregunta"]["ref"])
    assert vistas == [refs[0], refs[1], refs[2], refs[0]]


def test_la_unica_pasada_que_queda_vuelve_mientras_tenga_tiempo(reloj):
    evaluacion, _, navegador = preparar(preguntas=1, tiempo=30)
    intento_id = iniciado(navegador, evaluacion)
    ref = actual(navegador, intento_id).json()["pregunta"]["ref"]
    reloj.shift(10)
    otra_vez = pasar(navegador, intento_id, ref).json()
    assert otra_vez["ronda"] == 2
    assert otra_vez["pregunta"]["ref"] == ref
    assert otra_vez["pregunta"]["restante_ms"] == 20_000


def test_una_pregunta_pasada_sin_tiempo_no_vuelve(reloj):
    evaluacion, _, navegador = preparar(preguntas=2, tiempo=30)
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()["pregunta"]["ref"]
    # Pasa justo al agotarse (dentro de la tolerancia): ya no le queda tiempo.
    reloj.shift(31)
    segunda = pasar(navegador, intento_id, primera).json()
    assert _respuesta(primera).estado == EstadoRespuesta.SIN_TIEMPO
    responder(navegador, intento_id, segunda["pregunta"]["ref"], primera_alternativa(segunda))
    final = actual(navegador, intento_id).json()
    assert final["estado"] == "FINALIZADO"


# --- Tiempo agotado y tolerancia -----------------------------------------------------------------


def test_al_agotarse_el_tiempo_la_pregunta_queda_sin_tiempo_y_sigue_la_siguiente(reloj):
    evaluacion, _, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()["pregunta"]["ref"]
    reloj.shift(60)
    cuerpo = actual(navegador, intento_id).json()
    assert cuerpo["pregunta"]["numero"] == 2
    assert cuerpo["pregunta"]["restante_ms"] == 60_000
    agotada = _respuesta(primera)
    assert agotada.estado == EstadoRespuesta.SIN_TIEMPO
    assert agotada.segundos_usados == Decimal("60.000")
    assert agotada.alternativa is None


def test_una_respuesta_que_llega_dentro_de_la_tolerancia_se_acepta(reloj, settings):
    assert settings.RENDICION_TOLERANCIA_SEGUNDOS == 2
    evaluacion, _, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    reloj.shift(61.5)
    respuesta = responder_primera(navegador, intento_id, cuerpo)
    assert respuesta.status_code == 200
    guardada = _respuesta(cuerpo["pregunta"]["ref"])
    assert guardada.estado == EstadoRespuesta.RESPONDIDA
    # Nunca se registra más tiempo que el de la pregunta.
    assert guardada.segundos_usados == Decimal("60.000")


def test_una_respuesta_fuera_de_la_tolerancia_se_rechaza_y_la_pregunta_queda_sin_tiempo(reloj):
    evaluacion, _, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    reloj.shift(62.001)
    respuesta = responder_primera(navegador, intento_id, cuerpo)
    assert respuesta.status_code == 409
    assert respuesta.json() == {"codigo": "tiempo_agotado", "mensaje": "Se acabó el tiempo."}
    # El rechazo no deshace el paso del tiempo: SIN_TIEMPO quedó guardado.
    rechazada = _respuesta(cuerpo["pregunta"]["ref"])
    assert rechazada.estado == EstadoRespuesta.SIN_TIEMPO
    assert rechazada.alternativa is None
    assert actual(navegador, intento_id).json()["pregunta"]["numero"] == 2


def test_la_tolerancia_es_configurable(reloj, settings):
    settings.RENDICION_TOLERANCIA_SEGUNDOS = 0
    evaluacion, _, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    reloj.shift(60.5)
    respuesta = responder_primera(navegador, intento_id, cuerpo)
    assert respuesta.status_code == 409


# --- Desconexión -------------------------------------------------------------------------------


def test_tras_una_desconexion_corta_se_retoma_la_misma_pregunta_con_menos_tiempo(reloj):
    evaluacion, _, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    ref = actual(navegador, intento_id).json()["pregunta"]["ref"]
    # Sin peticiones durante 35 segundos: el tiempo sigue corriendo en el servidor.
    reloj.shift(35)
    otra_pestana = sesion_de(Intento.objects.get(pk=intento_id).alumno)
    vuelta = actual(otra_pestana, intento_id).json()
    assert vuelta["pregunta"]["ref"] == ref
    assert vuelta["pregunta"]["restante_ms"] == 25_000


def test_tras_una_desconexion_larga_la_pregunta_en_curso_se_pierde(reloj):
    evaluacion, _, navegador = preparar(preguntas=3, tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()
    responder(navegador, intento_id, primera["pregunta"]["ref"], primera_alternativa(primera))
    segunda = Intento.objects.get(pk=intento_id).respuestas.get(orden_presentacion=2)
    reloj.shift(150)
    vuelta = actual(navegador, intento_id).json()
    # La respuesta enviada antes de desconectarse quedó guardada.
    assert _respuesta(primera["pregunta"]["ref"]).estado == EstadoRespuesta.RESPONDIDA
    # La que estaba en curso se quedó sin tiempo; la siguiente parte de cero.
    assert _respuesta(segunda.id).estado == EstadoRespuesta.SIN_TIEMPO
    assert vuelta["pregunta"]["numero"] == 3
    assert vuelta["pregunta"]["restante_ms"] == 60_000


# --- Fin de la ventana -------------------------------------------------------------------------


def test_al_cerrar_la_ventana_el_intento_expira_en_la_siguiente_peticion(reloj):
    fin = INICIO + timedelta(seconds=90)
    evaluacion, alumno, navegador = preparar(preguntas=3, tiempo=60, fin=fin)
    intento_id = iniciado(navegador, evaluacion)
    primera = actual(navegador, intento_id).json()
    reloj.shift(30)
    pasar(navegador, intento_id, primera["pregunta"]["ref"])
    reloj.shift(70)  # 10 segundos después del fin de la ventana
    cuerpo = actual(navegador, intento_id).json()
    assert cuerpo["estado"] == "EXPIRADO"
    assert cuerpo["pregunta"] is None
    assert cuerpo["resumen"] == {"respondidas": 0, "total": 3}

    intento = Intento.objects.get(pk=intento_id)
    assert intento.estado == EstadoIntento.EXPIRADO
    assert intento.finalizado_en == INICIO + timedelta(seconds=100)
    estados = {r.orden_presentacion: r for r in intento.respuestas.all()}
    assert {r.estado for r in estados.values()} == {EstadoRespuesta.SIN_TIEMPO}
    # La segunda estaba en curso desde los 30 s: se cuenta solo hasta el fin (90 s).
    assert estados[2].segundos_usados == Decimal("60.000")
    assert estados[1].segundos_usados == Decimal("30.000")

    resultado = Resultado.objects.get(intento=intento)
    assert resultado.estado == EstadoResultado.CALCULADO
    assert resultado.nota == Decimal("1.0")
    registro = RegistroAuditoria.objects.get(accion=Accion.INTENTO_FINALIZADO)
    assert registro.actor == alumno
    assert registro.detalle == {"estado": "EXPIRADO"}


def test_cerca_del_fin_de_la_ventana_el_temporizador_muestra_lo_que_queda_de_la_ventana(reloj):
    evaluacion, _, navegador = preparar(tiempo=60, fin=INICIO + timedelta(seconds=25))
    intento_id = iniciado(navegador, evaluacion)
    pregunta = actual(navegador, intento_id).json()["pregunta"]
    assert pregunta["tiempo_total_ms"] == 60_000
    assert pregunta["restante_ms"] == 25_000


def test_responder_despues_del_fin_de_la_ventana_se_rechaza(reloj):
    evaluacion, _, navegador = preparar(fin=INICIO + timedelta(seconds=30))
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    reloj.shift(31)
    respuesta = responder_primera(navegador, intento_id, cuerpo)
    assert respuesta.status_code == 409
    assert Intento.objects.get(pk=intento_id).estado == EstadoIntento.EXPIRADO


def test_la_lista_de_pruebas_cierra_los_intentos_de_una_ventana_vencida(reloj):
    evaluacion, alumno, navegador = preparar(fin=INICIO + timedelta(minutes=10))
    intento_id = iniciado(navegador, evaluacion)
    actual(navegador, intento_id)
    reloj.shift(11 * 60)
    # El token de acceso dura 5 minutos: el frontend lo habría renovado.
    navegador = sesion_de(alumno)
    [fila] = navegador.get("/api/alumno/evaluaciones").json()["resultados"]
    assert fila["estado"] == "TERMINADA"
    assert Intento.objects.get(pk=intento_id).estado == EstadoIntento.EXPIRADO


# --- Fin normal ---------------------------------------------------------------------------------


def test_al_responder_la_ultima_el_intento_termina_y_se_calcula_el_resultado(reloj):
    evaluacion, alumno, navegador = preparar(preguntas=2)
    intento_id = iniciado(navegador, evaluacion)
    for _ in range(2):
        cuerpo = actual(navegador, intento_id).json()
        reloj.shift(3)
        final = responder_primera(navegador, intento_id, cuerpo)
    assert final.json() == {
        "estado": "FINALIZADO",
        "modalidad": "NOTIA",
        "ronda": 1,
        "voz": VOZ,
        "pregunta": None,
        "resumen": {"respondidas": 2, "total": 2},
    }
    resultado = Resultado.objects.get(asignacion__alumno=alumno)
    assert resultado.estado == EstadoResultado.CALCULADO
    # Volver a pedir la pregunta actual no cambia nada.
    assert actual(navegador, intento_id).json() == final.json()
    assert RegistroAuditoria.objects.filter(accion=Accion.INTENTO_FINALIZADO).count() == 1


def test_un_intento_terminado_no_acepta_mas_operaciones(reloj):
    evaluacion, _, navegador = preparar(preguntas=1)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    ref = cuerpo["pregunta"]["ref"]
    responder(navegador, intento_id, ref, primera_alternativa(cuerpo))
    assert pasar(navegador, intento_id, ref).status_code == 409
    assert navegador.enviar(f"/api/alumno/respuestas/{ref}/repeticion").status_code == 409
    assert cambiar_voz(navegador, intento_id, OTRA_VOZ).status_code == 409


# --- Voz y repeticiones ------------------------------------------------------------


def test_cambiar_la_voz_no_reinicia_el_tiempo(reloj):
    evaluacion, alumno, navegador = preparar(tiempo=60)
    intento_id = iniciado(navegador, evaluacion)
    actual(navegador, intento_id)
    reloj.shift(20)
    respuesta = cambiar_voz(navegador, intento_id, OTRA_VOZ)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"voz": OTRA_VOZ}
    cuerpo = actual(navegador, intento_id).json()
    assert cuerpo["voz"] == OTRA_VOZ
    assert cuerpo["pregunta"]["restante_ms"] == 40_000
    alumno.refresh_from_db()
    assert alumno.voz_preferida == OTRA_VOZ


def test_no_se_cambia_a_una_voz_que_no_existe(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    assert cambiar_voz(navegador, intento_id, "en-US-JennyNeural").status_code == 400
    assert Intento.objects.get(pk=intento_id).voz == VOZ


def test_en_modalidad_normal_no_hay_voz_que_cambiar(reloj):
    evaluacion, _, navegador = preparar(modalidad=Modalidad.NORMAL)
    intento_id = iniciado(navegador, evaluacion, voz=None)
    respuesta = cambiar_voz(navegador, intento_id, OTRA_VOZ)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "sin_audio"


def test_cada_repeticion_del_audio_se_cuenta(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    ref = actual(navegador, intento_id).json()["pregunta"]["ref"]
    for _ in range(3):
        assert navegador.enviar(f"/api/alumno/respuestas/{ref}/repeticion").status_code == 204
    assert _respuesta(ref).repeticiones_audio == 3


def test_no_se_cuentan_repeticiones_de_una_pregunta_que_no_esta_en_curso(reloj):
    evaluacion, _, navegador = preparar()
    intento_id = iniciado(navegador, evaluacion)
    actual(navegador, intento_id)
    tercera = Intento.objects.get(pk=intento_id).respuestas.get(orden_presentacion=3)
    ruta = f"/api/alumno/respuestas/{tercera.id}/repeticion"
    assert navegador.enviar(ruta).status_code == 409
    assert _respuesta(tercera.id).repeticiones_audio == 0


# --- La lista de pruebas ------------------------------------------------------------


def test_la_lista_muestra_el_estado_de_cada_prueba(reloj):
    alumno = crear_alumno()
    navegador = sesion_de(alumno)
    disponible = crear_evaluacion(preguntas=2, publicada=True, titulo="Disponible")
    proxima = crear_evaluacion(
        preguntas=1,
        publicada=True,
        titulo="Próxima",
        inicio=INICIO + timedelta(days=1),
        fin=INICIO + timedelta(days=2),
    )
    vencida = crear_evaluacion(
        preguntas=1,
        publicada=True,
        titulo="Vencida",
        inicio=INICIO - timedelta(days=2),
        fin=INICIO - timedelta(days=1),
    )
    borrador = crear_evaluacion(preguntas=1, titulo="Borrador")
    for evaluacion in (disponible, proxima, vencida, borrador):
        asignar(evaluacion, alumno)
    crear_evaluacion(preguntas=1, publicada=True, titulo="De otro curso")

    filas = {f["titulo"]: f for f in navegador.get("/api/alumno/evaluaciones").json()["resultados"]}
    assert set(filas) == {"Disponible", "Próxima", "Vencida"}
    assert filas["Disponible"]["estado"] == "DISPONIBLE"
    assert filas["Disponible"]["preguntas"] == 2
    assert filas["Disponible"]["intento"] is None
    assert filas["Próxima"]["estado"] == "PROXIMA"
    assert filas["Vencida"]["estado"] == "VENCIDA"

    intento_id = iniciado(navegador, disponible)
    filas = {f["titulo"]: f for f in navegador.get("/api/alumno/evaluaciones").json()["resultados"]}
    assert filas["Disponible"]["estado"] == "EN_CURSO"
    assert filas["Disponible"]["intento"] == intento_id
