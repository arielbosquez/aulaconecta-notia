"""Peticiones simultáneas contra PostgreSQL real (sección 7.1, regla 15).

Cada petición corre en su propio hilo y con su propia conexión a la base,
como cada worker de gunicorn en producción, y todas parten a la vez. Con
``bd_con_transacciones`` cada operación se confirma de verdad, así que los
hilos compiten por las mismas filas y el bloqueo (``SELECT … FOR UPDATE``)
es lo único que los ordena.

Las pruebas corren como ``notia_app``. Al terminar, pytest-django vacía las
tablas con ``TRUNCATE``, que ``notia_app`` no tiene: ese vaciado (y solo ese)
lo hace ``notia_owner``, como explica el fixture en ``backend/conftest.py``.
"""

import threading

from django.db import connections

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.evaluaciones.tests.fabricas import sesion_de
from apps.rendicion.models import EstadoRespuesta, Intento, Respuesta

from .ayudantes import actual, iniciado, iniciar, pasar, preparar, responder

HILOS = 6


def _en_paralelo(funciones) -> list:
    """Ejecuta cada función en su hilo; todas parten al mismo tiempo."""
    barrera = threading.Barrier(len(funciones))
    resultados: list = [None] * len(funciones)
    errores = []

    def trabajo(indice, funcion):
        try:
            barrera.wait(timeout=30)
            resultados[indice] = funcion()
        except Exception as error:  # se informa en el hilo principal
            errores.append(error)
        finally:
            connections.close_all()

    hilos = [
        threading.Thread(target=trabajo, args=(indice, funcion))
        for indice, funcion in enumerate(funciones)
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=120)
    assert not errores, errores
    return resultados


def _navegadores(alumno, cantidad):
    """Una pestaña por hilo, cada una con su propia sesión."""
    return [sesion_de(alumno) for _ in range(cantidad)]


def test_la_misma_respuesta_enviada_a_la_vez_se_guarda_una_sola_vez(bd_con_transacciones):
    evaluacion, alumno, navegador = preparar(preguntas=3)
    intento_id = iniciado(navegador, evaluacion)
    pregunta = actual(navegador, intento_id).json()["pregunta"]
    alternativas = [a["id"] for a in pregunta["alternativas"]]

    pestanas = _navegadores(alumno, HILOS)
    respuestas = _en_paralelo(
        [
            (lambda p=pestana, i=n: responder(p, intento_id, pregunta["ref"], alternativas[i % 4]))
            for n, pestana in enumerate(pestanas)
        ]
    )
    estados = sorted(r.status_code for r in respuestas)
    assert estados == [200] + [409] * (HILOS - 1)
    ganadora = next(r for r in respuestas if r.status_code == 200)
    guardada = Respuesta.objects.get(pk=pregunta["ref"])
    assert guardada.estado == EstadoRespuesta.RESPONDIDA
    # La alternativa guardada es la de la petición que ganó, y no cambió después.
    indice = respuestas.index(ganadora)
    assert str(guardada.alternativa_id) == alternativas[indice % 4]
    # Se presentó una sola pregunta siguiente.
    intento = Intento.objects.get(pk=intento_id)
    assert intento.respuestas.filter(estado=EstadoRespuesta.EN_CURSO).count() == 1
    assert ganadora.json()["pregunta"]["numero"] == 2


def test_responder_y_pasar_a_la_vez_solo_cuenta_lo_primero(bd_con_transacciones):
    evaluacion, alumno, navegador = preparar(preguntas=2)
    intento_id = iniciado(navegador, evaluacion)
    pregunta = actual(navegador, intento_id).json()["pregunta"]
    una, otra = _navegadores(alumno, 2)
    respuestas = _en_paralelo(
        [
            lambda: responder(una, intento_id, pregunta["ref"], pregunta["alternativas"][0]["id"]),
            lambda: pasar(otra, intento_id, pregunta["ref"]),
        ]
    )
    assert sorted(r.status_code for r in respuestas) == [200, 409]
    estado = Respuesta.objects.get(pk=pregunta["ref"]).estado
    assert estado in (EstadoRespuesta.RESPONDIDA, EstadoRespuesta.PASADA)
    intento = Intento.objects.get(pk=intento_id)
    assert intento.respuestas.filter(estado=EstadoRespuesta.EN_CURSO).count() == 1


def test_varias_pestanas_pidiendo_la_pregunta_actual_ven_la_misma(bd_con_transacciones):
    evaluacion, alumno, navegador = preparar(preguntas=4)
    intento_id = iniciado(navegador, evaluacion)
    respuestas = _en_paralelo(
        [(lambda p=p: actual(p, intento_id)) for p in _navegadores(alumno, HILOS)]
    )
    assert {r.status_code for r in respuestas} == {200}
    assert len({r.json()["pregunta"]["ref"] for r in respuestas}) == 1
    intento = Intento.objects.get(pk=intento_id)
    assert intento.respuestas.filter(estado=EstadoRespuesta.EN_CURSO).count() == 1


def test_varios_clics_en_empezar_crean_un_solo_intento(bd_con_transacciones):
    evaluacion, alumno, _ = preparar(preguntas=2)
    respuestas = _en_paralelo(
        [(lambda p=p: iniciar(p, evaluacion)) for p in _navegadores(alumno, HILOS)]
    )
    estados = sorted(r.status_code for r in respuestas)
    assert estados == [201] + [409] * (HILOS - 1)
    assert Intento.objects.filter(alumno=alumno).count() == 1
    assert Respuesta.objects.filter(intento__alumno=alumno).count() == 2
    assert RegistroAuditoria.objects.filter(accion=Accion.INTENTO_INICIADO).count() == 1
