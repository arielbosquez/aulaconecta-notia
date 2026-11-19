"""Eventos de integridad y avisos del alumno (CU-05, CU-08; RS-07 y RS-10).

Lo que se prueba: la lista cerrada de tipos, los límites (20 por envío y 60
por minuto por intento, exacto aunque lleguen lotes a la vez) y que ni los
eventos ni los avisos acepten texto libre.
"""

import threading

import pytest
import time_machine
from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.evaluaciones.models import EstadoEvaluacion
from apps.evaluaciones.tests.fabricas import (
    asignar,
    crear_alumno,
    crear_docente,
    crear_evaluacion,
    sesion_de,
)
from apps.integridad.models import (
    EstadoSolicitud,
    EventoIntegridad,
    SolicitudAlumno,
    TipoEvento,
    TipoSolicitud,
)
from apps.rendicion.models import Intento
from apps.rendicion.tests.ayudantes import actual, iniciado, preparar, responder_primera


def _enviar(navegador, intento_id, *eventos):
    ruta = f"/api/alumno/intentos/{intento_id}/eventos"
    return navegador.enviar(ruta, {"eventos": list(eventos)})


def _evento(tipo=TipoEvento.SALIO_DE_PESTANA, **campos):
    return {"tipo": str(tipo), **campos}


@pytest.fixture
def en_prueba(db):
    """Un alumno con su intento en curso y la primera pregunta presentada."""
    evaluacion, alumno, navegador = preparar(preguntas=2)
    intento_id = iniciado(navegador, evaluacion)
    cuerpo = actual(navegador, intento_id).json()
    return evaluacion, alumno, navegador, intento_id, cuerpo


# --- Eventos ----------------------------------------------------------------------------------


def test_un_lote_de_eventos_se_guarda_con_la_hora_del_servidor_y_la_pregunta_en_curso(en_prueba):
    _, _, navegador, intento_id, cuerpo = en_prueba
    # La hora queda congelada en este instante: la ventana de la prueba está abierta.
    ahora = timezone.now()
    with time_machine.travel(ahora, tick=False):
        respuesta = _enviar(
            navegador,
            intento_id,
            _evento(TipoEvento.SALIO_DE_PESTANA),
            _evento(TipoEvento.VOLVIO_A_PESTANA, duracion_ms=4200),
        )
    assert respuesta.status_code == 201
    assert respuesta.json() == {"registrados": 2}
    eventos = list(EventoIntegridad.objects.order_by("id"))
    assert [e.tipo for e in eventos] == ["SALIO_DE_PESTANA", "VOLVIO_A_PESTANA"]
    assert [e.duracion_ms for e in eventos] == [None, 4200]
    assert {e.registrado_en for e in eventos} == {ahora}
    assert {str(e.respuesta_id) for e in eventos} == {cuerpo["pregunta"]["ref"]}
    assert not any(e.revisado for e in eventos)


def test_se_aceptan_los_11_tipos_de_la_lista(en_prueba):
    _, _, navegador, intento_id, _ = en_prueba
    respuesta = _enviar(navegador, intento_id, *[_evento(tipo) for tipo in TipoEvento])
    assert respuesta.status_code == 201
    assert EventoIntegridad.objects.count() == len(TipoEvento) == 11


@pytest.mark.parametrize(
    "evento",
    [
        {"tipo": "CAPTURA_DE_PANTALLA"},
        {"tipo": "salio_de_pestana"},
        {"tipo": ""},
        {"tipo": None},
        {},
        {"tipo": "INTENTO_COPIAR", "texto": "lo que copió el alumno"},
        {"tipo": "INTENTO_COPIAR", "registrado_en": "2020-01-01T00:00:00Z"},
        {"tipo": "INTENTO_COPIAR", "respuesta": "00000000-0000-0000-0000-000000000000"},
        {"tipo": "PERDIO_FOCO", "duracion_ms": -1},
        {"tipo": "PERDIO_FOCO", "duracion_ms": 24 * 60 * 60 * 1000 + 1},
        {"tipo": "PERDIO_FOCO", "duracion_ms": "mucho"},
        "SALIO_DE_PESTANA",
    ],
)
def test_un_evento_fuera_de_la_lista_o_con_campos_de_mas_se_rechaza_con_todo_el_lote(
    en_prueba, evento
):
    _, _, navegador, intento_id, _ = en_prueba
    respuesta = _enviar(navegador, intento_id, _evento(), evento)
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "datos_invalidos"
    assert not EventoIntegridad.objects.exists()


@pytest.mark.parametrize("cuerpo", [{}, {"eventos": []}, {"eventos": "x"}, {"eventos": [], "x": 1}])
def test_un_envio_sin_eventos_se_rechaza(en_prueba, cuerpo):
    _, _, navegador, intento_id, _ = en_prueba
    ruta = f"/api/alumno/intentos/{intento_id}/eventos"
    assert navegador.enviar(ruta, cuerpo).status_code == 400


def test_hasta_20_eventos_por_envio(en_prueba):
    _, _, navegador, intento_id, _ = en_prueba
    assert _enviar(navegador, intento_id, *[_evento()] * 20).status_code == 201
    assert _enviar(navegador, intento_id, *[_evento()] * 21).status_code == 400
    assert EventoIntegridad.objects.count() == 20


def test_mas_de_60_eventos_por_minuto_se_rechazan_con_429(en_prueba):
    _, _, navegador, intento_id, _ = en_prueba
    with time_machine.travel(timezone.now(), tick=False) as reloj:
        for _ in range(3):
            assert _enviar(navegador, intento_id, *[_evento()] * 20).status_code == 201
        reloj.shift(30)
        rechazo = _enviar(navegador, intento_id, _evento())
        assert rechazo.status_code == 429
        assert rechazo.json()["codigo"] == "demasiados_eventos"
        assert EventoIntegridad.objects.count() == 60
        # Pasado el minuto desde los primeros, vuelve a haber espacio.
        reloj.shift(31)
        assert _enviar(navegador, intento_id, _evento()).status_code == 201
        assert EventoIntegridad.objects.count() == 61


def test_un_lote_que_supera_el_limite_no_se_guarda_a_medias(en_prueba):
    _, _, navegador, intento_id, _ = en_prueba
    for _ in range(2):
        _enviar(navegador, intento_id, *[_evento()] * 20)
    _enviar(navegador, intento_id, *[_evento()] * 15)
    assert _enviar(navegador, intento_id, *[_evento()] * 10).status_code == 429
    assert EventoIntegridad.objects.count() == 55


def test_el_limite_es_por_intento(en_prueba):
    evaluacion, _, navegador, intento_id, _ = en_prueba
    for _ in range(3):
        _enviar(navegador, intento_id, *[_evento()] * 20)
    otro = crear_alumno()
    asignar(evaluacion, otro)
    navegador_otro = sesion_de(otro)
    intento_otro = iniciado(navegador_otro, evaluacion)
    assert _enviar(navegador_otro, intento_otro, _evento()).status_code == 201


def test_no_se_registran_eventos_de_un_intento_terminado(en_prueba):
    _, _, navegador, intento_id, cuerpo = en_prueba
    siguiente = responder_primera(navegador, intento_id, cuerpo).json()
    responder_primera(navegador, intento_id, siguiente)
    respuesta = _enviar(navegador, intento_id, _evento())
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "intento_terminado"
    assert not EventoIntegridad.objects.exists()


def test_otro_alumno_no_puede_registrar_eventos_en_un_intento_ajeno(en_prueba):
    _, _, _, intento_id, _ = en_prueba
    intruso = crear_alumno()
    respuesta = _enviar(sesion_de(intruso), intento_id, _evento(TipoEvento.INTENTO_PEGAR))
    assert respuesta.status_code == 404
    assert not EventoIntegridad.objects.exists()
    registro = RegistroAuditoria.objects.get(accion=Accion.ACCESO_DENEGADO, actor=intruso)
    assert registro.detalle["objeto_tipo"] == "rendicion.Intento"


def test_un_docente_no_registra_eventos(en_prueba):
    _, _, _, intento_id, _ = en_prueba
    assert _enviar(sesion_de(crear_docente()), intento_id, _evento()).status_code == 403
    assert not EventoIntegridad.objects.exists()


def test_los_eventos_exigen_csrf(en_prueba):
    _, _, navegador, intento_id, _ = en_prueba
    ruta = f"/api/alumno/intentos/{intento_id}/eventos"
    assert navegador.enviar(ruta, {"eventos": [_evento()]}, con_csrf=False).status_code == 403


def test_el_modelo_de_eventos_no_tiene_campos_de_texto():
    campos = {campo.name for campo in EventoIntegridad._meta.get_fields() if campo.concrete}
    assert campos == {
        "id",
        "intento",
        "respuesta",
        "tipo",
        "duracion_ms",
        "registrado_en",
        "revisado",
    }


def test_la_base_rechaza_un_tipo_fuera_de_la_lista(en_prueba):
    intento = Intento.objects.get(pk=en_prueba[3])
    with pytest.raises(IntegrityError), transaction.atomic():
        EventoIntegridad.objects.create(intento=intento, tipo="OTRO")


def test_lotes_simultaneos_respetan_el_limite_exacto(bd_con_transacciones):
    """Cuatro lotes de 20 a la vez: entran 3 (60 eventos) y el cuarto recibe 429."""
    evaluacion, alumno, navegador = preparar(preguntas=1)
    intento_id = iniciado(navegador, evaluacion)
    actual(navegador, intento_id)
    pestanas = [sesion_de(alumno) for _ in range(4)]
    barrera = threading.Barrier(len(pestanas))
    estados, errores = [], []

    def enviar(pestana):
        try:
            barrera.wait(timeout=30)
            estados.append(_enviar(pestana, intento_id, *[_evento()] * 20).status_code)
        except Exception as error:  # se informa en el hilo principal
            errores.append(error)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=enviar, args=(p,)) for p in pestanas]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=120)
    assert not errores, errores
    assert sorted(estados) == [201, 201, 201, 429]
    assert EventoIntegridad.objects.filter(intento_id=intento_id).count() == 60


# --- Avisos al docente (CU-08) -------------------------------------------------------------------


def _avisar(navegador, evaluacion, tipo=TipoSolicitud.NINGUNA_VOZ_SIRVE, **extra):
    datos = {"evaluacion": str(evaluacion.id), "tipo": str(tipo), **extra}
    return navegador.enviar("/api/alumno/solicitudes", datos)


@pytest.fixture
def asignada(db):
    evaluacion = crear_evaluacion(preguntas=1, publicada=True)
    alumno = crear_alumno()
    asignar(evaluacion, alumno)
    return evaluacion, alumno, sesion_de(alumno)


def test_el_alumno_avisa_que_ninguna_voz_le_sirve(asignada):
    evaluacion, alumno, navegador = asignada
    respuesta = _avisar(navegador, evaluacion)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"id", "evaluacion", "tipo", "estado", "creada_en"}
    assert cuerpo["tipo"] == "NINGUNA_VOZ_SIRVE"
    assert cuerpo["estado"] == "PENDIENTE"
    solicitud = SolicitudAlumno.objects.get(pk=cuerpo["id"])
    assert solicitud.alumno == alumno
    assert solicitud.evaluacion == evaluacion


def test_repetir_un_aviso_pendiente_no_crea_otro(asignada):
    evaluacion, _, navegador = asignada
    primero = _avisar(navegador, evaluacion).json()
    repetido = _avisar(navegador, evaluacion)
    assert repetido.status_code == 200
    assert repetido.json()["id"] == primero["id"]
    otro = _avisar(navegador, evaluacion, TipoSolicitud.NECESITO_OTRA_MODALIDAD)
    assert otro.status_code == 201
    assert SolicitudAlumno.objects.count() == 2


def test_un_aviso_atendido_se_puede_volver_a_enviar(asignada):
    evaluacion, _, navegador = asignada
    primero = _avisar(navegador, evaluacion).json()
    SolicitudAlumno.objects.filter(pk=primero["id"]).update(
        estado=EstadoSolicitud.ATENDIDA, atendida_por=evaluacion.creada_por
    )
    nuevo = _avisar(navegador, evaluacion)
    assert nuevo.status_code == 201
    assert nuevo.json()["id"] != primero["id"]


@pytest.mark.parametrize(
    "extra",
    [
        {"mensaje": "Tengo un problema de audición"},
        {"texto": "Necesito más tiempo"},
        {"motivo": "dato de salud"},
        {"detalle": "x"},
    ],
)
def test_un_aviso_no_acepta_texto_libre(asignada, extra):
    evaluacion, _, navegador = asignada
    respuesta = _avisar(navegador, evaluacion, **extra)
    assert respuesta.status_code == 400
    assert not SolicitudAlumno.objects.exists()


@pytest.mark.parametrize("tipo", ["OTRA_COSA", "", "ninguna_voz_sirve"])
def test_un_aviso_de_tipo_desconocido_se_rechaza(asignada, tipo):
    evaluacion, _, navegador = asignada
    assert _avisar(navegador, evaluacion, tipo).status_code == 400


def test_no_se_avisa_sobre_una_prueba_no_asignada(asignada):
    _, _, navegador = asignada
    ajena = crear_evaluacion(preguntas=1, publicada=True)
    assert _avisar(navegador, ajena).status_code == 404
    borrador = crear_evaluacion(preguntas=1)
    assert _avisar(navegador, borrador).status_code == 404
    assert not SolicitudAlumno.objects.exists()


def test_tampoco_sobre_una_asignada_que_sigue_en_borrador(asignada):
    evaluacion, _, navegador = asignada
    evaluacion.estado = EstadoEvaluacion.BORRADOR
    evaluacion.publicada_en = None
    evaluacion.save()
    assert _avisar(navegador, evaluacion).status_code == 404


def test_un_docente_no_envia_avisos_de_alumno(asignada):
    evaluacion = asignada[0]
    assert _avisar(sesion_de(crear_docente()), evaluacion).status_code == 403


def test_el_modelo_de_avisos_no_tiene_campos_de_texto():
    campos = {campo.name for campo in SolicitudAlumno._meta.get_fields() if campo.concrete}
    assert campos == {"id", "alumno", "evaluacion", "tipo", "estado", "creada_en", "atendida_por"}


def test_la_base_impide_dos_avisos_pendientes_iguales(asignada):
    evaluacion, alumno, _ = asignada
    SolicitudAlumno.objects.create(alumno=alumno, evaluacion=evaluacion, tipo="NINGUNA_VOZ_SIRVE")
    with pytest.raises(IntegrityError), transaction.atomic():
        SolicitudAlumno.objects.create(
            alumno=alumno, evaluacion=evaluacion, tipo="NINGUNA_VOZ_SIRVE"
        )


def test_la_base_exige_quien_atendio_el_aviso(asignada):
    evaluacion, alumno, _ = asignada
    solicitud = SolicitudAlumno.objects.create(
        alumno=alumno, evaluacion=evaluacion, tipo="NECESITO_OTRA_MODALIDAD"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SolicitudAlumno.objects.filter(pk=solicitud.pk).update(estado=EstadoSolicitud.ATENDIDA)
