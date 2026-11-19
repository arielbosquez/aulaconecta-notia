"""``fn_calcular_resultado`` contra una implementación de referencia en Python (sección 9).

La referencia existe solo para estas pruebas: calcula con fracciones exactas
y redondea al final, como se calcula una nota a mano. La función de
PostgreSQL debe dar exactamente lo mismo en cada caso.
"""

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

import pytest
from django.db import connection
from django.utils import timezone

from apps.evaluaciones.tests.fabricas import (
    asignar,
    crear_alumno,
    crear_evaluacion,
    crear_pregunta,
    sesion_de,
)
from apps.rendicion import motor
from apps.rendicion.models import EstadoIntento, EstadoRespuesta, Intento
from apps.rendicion.servicios import crear_intento
from apps.resultados.models import EstadoResultado, Resultado
from apps.resultados.servicios import calcular

pytestmark = pytest.mark.django_db


def _redondear(valor: Fraction, decimales: str) -> Decimal:
    exacto = Decimal(valor.numerator) / Decimal(valor.denominator)
    return exacto.quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def referencia(obtenido, total, exigencia=60, minima="1.0", maxima="7.0"):
    """(porcentaje, nota) calculados a mano con la fórmula de la sección 9."""
    if total == 0:
        return None, None
    p = Fraction(obtenido, total)
    e = Fraction(exigencia, 100)
    minima, maxima = Fraction(minima), Fraction(maxima)
    if p < e:
        nota = minima + (4 - minima) * p / e
    else:
        nota = 4 + (maxima - 4) * (p - e) / (1 - e)
    return _redondear(100 * p, "0.01"), _redondear(nota, "0.1")


def _rendir(puntajes, correctas, *, anuladas=(), sin_responder=(), **campos_evaluacion):
    """Intento con preguntas de esos puntajes, respondidas según ``correctas``.

    ``correctas[i]`` indica si la pregunta i se respondió bien. Las de
    ``sin_responder`` quedan sin tiempo.
    """
    evaluacion = crear_evaluacion(publicada=True, **campos_evaluacion)
    for orden, puntaje in enumerate(puntajes, start=1):
        crear_pregunta(evaluacion, orden=orden, puntaje=puntaje, anulada=orden - 1 in anuladas)
    alumno = crear_alumno()
    intento = crear_intento(asignar(evaluacion, alumno), voz="es-CL-CatalinaNeural")
    ahora = timezone.now()
    for respuesta in intento.respuestas.select_related("pregunta"):
        indice = respuesta.pregunta.orden - 1
        if indice in sin_responder:
            respuesta.estado = EstadoRespuesta.SIN_TIEMPO
        else:
            alternativas = respuesta.pregunta.alternativas
            respuesta.alternativa = alternativas.filter(es_correcta=correctas[indice]).first()
            respuesta.estado = EstadoRespuesta.RESPONDIDA
            respuesta.respondida_en = ahora
        respuesta.save()
    return intento


def _comparar(intento, obtenido, total, **escala):
    calculo = calcular(intento.id)
    porcentaje, nota = referencia(obtenido, total, **escala)
    assert calculo.puntaje_obtenido == obtenido
    assert calculo.puntaje_total == total
    assert calculo.porcentaje == porcentaje
    assert calculo.nota == nota
    return calculo


def test_0_por_ciento_es_la_nota_minima():
    intento = _rendir([1] * 10, [False] * 10)
    assert _comparar(intento, 0, 10).nota == Decimal("1.0")


def test_59_por_ciento_queda_bajo_el_4():
    intento = _rendir([59, 41], [True, False])
    calculo = _comparar(intento, 59, 100)
    # 1 + 3 × 0,59 / 0,6 = 3,95, que se redondea a 4,0 pero con logro bajo la exigencia.
    assert calculo.porcentaje == Decimal("59.00")
    assert calculo.nota == Decimal("4.0")


def test_58_por_ciento_es_un_3_9():
    intento = _rendir([58, 42], [True, False])
    assert _comparar(intento, 58, 100).nota == Decimal("3.9")


def test_con_60_por_ciento_de_exigencia_el_60_por_ciento_es_un_4():
    intento = _rendir([60, 40], [True, False])
    assert _comparar(intento, 60, 100).nota == Decimal("4.0")


def test_100_por_ciento_es_la_nota_maxima():
    intento = _rendir([1] * 5, [True] * 5)
    assert _comparar(intento, 5, 5).nota == Decimal("7.0")


def test_las_preguntas_anuladas_no_cuentan():
    # La anulada (la segunda) se respondió mal, pero no suma al total.
    intento = _rendir([2, 3, 5], [True, False, True], anuladas=(1,))
    assert _comparar(intento, 7, 7).nota == Decimal("7.0")


def test_una_anulada_respondida_bien_tampoco_suma():
    intento = _rendir([4, 6], [True, False], anuladas=(0,))
    assert _comparar(intento, 0, 6).nota == Decimal("1.0")


def test_si_todas_estan_anuladas_no_hay_nota():
    intento = _rendir([1, 1], [True, True], anuladas=(0, 1))
    calculo = calcular(intento.id)
    assert calculo.puntaje_total == 0
    assert calculo.porcentaje is None
    assert calculo.nota is None


def test_las_preguntas_sin_responder_valen_cero():
    intento = _rendir([1, 1, 1], [True, True, True], sin_responder=(2,))
    _comparar(intento, 2, 3)


@pytest.mark.parametrize(
    ("exigencia", "minima", "maxima"),
    [(50, "1.0", "7.0"), (70, "1.0", "7.0"), (60, "2.0", "7.0"), (60, "1.0", "6.0")],
)
@pytest.mark.parametrize("correctas", [0, 1, 3, 4, 5, 6, 7])
def test_otras_escalas_coinciden_con_la_referencia(exigencia, minima, maxima, correctas):
    intento = _rendir(
        [1] * 7,
        [i < correctas for i in range(7)],
        exigencia=exigencia,
        nota_minima=Decimal(minima),
        nota_maxima=Decimal(maxima),
    )
    _comparar(intento, correctas, 7, exigencia=exigencia, minima=minima, maxima=maxima)


def test_un_porcentaje_periodico_se_redondea_igual_que_la_referencia():
    intento = _rendir([1, 1, 1], [True, False, False])
    calculo = _comparar(intento, 1, 3)
    assert calculo.porcentaje == Decimal("33.33")


def test_un_intento_inexistente_no_tiene_resultado():
    import uuid

    calculo = calcular(uuid.uuid4())
    assert calculo.nota is None and calculo.puntaje_total is None


# --- La función en la base de datos --------------------------------------------------


def _funcion():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.provolatile, p.prosecdef, p.proconfig, p.prosrc, "
            "       has_function_privilege('notia_app', p.oid, 'EXECUTE'), "
            "       pg_get_userbyid(p.proowner), "
            "       coalesce(p.proacl::text, '') "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname = 'fn_calcular_resultado'"
        )
        return cursor.fetchone()


def test_la_funcion_es_stable_sin_privilegios_de_dueno_y_con_search_path_fijo():
    volatilidad, privilegios_de_dueno, configuracion, _, _, dueno, _ = _funcion()
    assert volatilidad == "s"  # STABLE
    assert privilegios_de_dueno is False  # SECURITY INVOKER
    assert configuracion == ["search_path=pg_catalog, pg_temp"]
    assert dueno == "notia_owner"


def test_la_funcion_no_tiene_sql_dinamico():
    codigo = _funcion()[3].upper()
    assert "EXECUTE" not in codigo
    assert "FORMAT(" not in codigo


def test_solo_notia_app_puede_ejecutarla():
    *_, notia_app_puede, _, permisos = _funcion()
    assert notia_app_puede is True
    # Ningún permiso para PUBLIC: en el ACL no hay una entrada "=X/…".
    assert not any(entrada.startswith("=") for entrada in permisos.strip("{}").split(","))


# --- El resultado al terminar ---------------------------------------------------------


def test_al_terminar_el_intento_queda_el_resultado_calculado():
    intento = _rendir([1, 1], [True, False])
    # Las dos respuestas ya están dadas: presentar no encuentra más y finaliza.
    with motor.transaction.atomic():
        motor.presentar(motor.bloquear(Intento.objects.filter(pk=intento.pk)), timezone.now())
    intento.refresh_from_db()
    assert intento.estado == EstadoIntento.FINALIZADO
    resultado = Resultado.objects.get(intento=intento)
    assert resultado.estado == EstadoResultado.CALCULADO
    assert resultado.porcentaje == Decimal("50.00")
    assert resultado.nota == referencia(1, 2)[1]
    assert resultado.calculado_en is not None


def test_el_alumno_no_ve_la_nota_hasta_que_se_publica():
    intento = _rendir([1, 1], [True, True])
    with motor.transaction.atomic():
        motor.presentar(motor.bloquear(Intento.objects.filter(pk=intento.pk)), timezone.now())
    navegador = sesion_de(intento.alumno)
    assert navegador.get("/api/alumno/resultados").json() == {"resultados": []}

    resultado = Resultado.objects.get(intento=intento)
    resultado.estado = EstadoResultado.PUBLICADO
    resultado.publicado_en = timezone.now()
    resultado.save()
    [publicado] = navegador.get("/api/alumno/resultados").json()["resultados"]
    assert publicado["nota"] == "7.0"
    assert publicado["evaluacion"]["id"] == str(intento.evaluacion_id)
    assert set(publicado) == {"evaluacion", "nota", "porcentaje", "publicado_en"}


def test_un_alumno_no_ve_los_resultados_publicados_de_otro():
    intento = _rendir([1], [True])
    with motor.transaction.atomic():
        motor.presentar(motor.bloquear(Intento.objects.filter(pk=intento.pk)), timezone.now())
    Resultado.objects.filter(intento=intento).update(
        estado=EstadoResultado.PUBLICADO, publicado_en=timezone.now()
    )
    otro = crear_alumno()
    assert sesion_de(otro).get("/api/alumno/resultados").json() == {"resultados": []}

