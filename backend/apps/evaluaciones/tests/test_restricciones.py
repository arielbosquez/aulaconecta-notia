"""Restricciones de cursos, evaluaciones, preguntas, alternativas y asignaciones.

Las que puede garantizar la base de datos se prueban contra PostgreSQL: se
salta el modelo a propósito (``update`` o ``create`` directos) para comprobar
que la base las rechaza aunque el código tenga un error. Las que dependen de
contar filas se prueban con ``apps.evaluaciones.validaciones``.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.db.models import ProtectedError

from apps.academico.models import Curso, CursoDocente, Matricula
from apps.evaluaciones.models import (
    Alternativa,
    AsignacionPrueba,
    EstadoEvaluacion,
    Evaluacion,
    Modalidad,
    Pregunta,
)
from apps.evaluaciones.validaciones import validar_para_publicar, validar_pregunta

from .fabricas import (
    asignar,
    crear_alumno,
    crear_curso,
    crear_docente,
    crear_evaluacion,
    crear_pregunta,
)

pytestmark = pytest.mark.django_db


def _rechazada(funcion, error=IntegrityError):
    """Comprueba que la base de datos rechaza la operación."""
    with pytest.raises(error), transaction.atomic():
        funcion()


# --- Cursos y matrículas -------------------------------------------------------


def test_un_curso_es_unico_por_nombre_y_anio():
    crear_curso(nombre="2° Medio A", anio=2026)
    crear_curso(nombre="2° Medio A", anio=2027)
    _rechazada(lambda: Curso.objects.create(nombre="2° Medio A", anio=2026))


@pytest.mark.parametrize("anio", [2019, 2101])
def test_el_anio_del_curso_debe_ser_razonable(anio):
    _rechazada(lambda: Curso.objects.create(nombre="1° Básico", anio=anio))


def test_el_curso_necesita_nombre():
    _rechazada(lambda: Curso.objects.create(nombre="   ", anio=2026))


def test_un_alumno_se_matricula_una_sola_vez_por_curso():
    curso, alumno = crear_curso(), crear_alumno()
    Matricula.objects.create(curso=curso, alumno=alumno)
    _rechazada(lambda: Matricula.objects.create(curso=curso, alumno=alumno, activa=False))


def test_un_docente_dicta_cada_asignatura_una_vez_por_curso():
    curso, docente = crear_curso(), crear_docente()
    CursoDocente.objects.create(curso=curso, docente=docente, asignatura="Historia")
    CursoDocente.objects.create(curso=curso, docente=docente, asignatura="Lenguaje")
    _rechazada(
        lambda: CursoDocente.objects.create(curso=curso, docente=docente, asignatura="Historia")
    )


# --- Evaluaciones ------------------------------------------------------------------


def test_valores_por_omision_de_la_arquitectura():
    evaluacion = crear_evaluacion()
    assert evaluacion.estado == EstadoEvaluacion.BORRADOR
    assert evaluacion.version == 1
    assert evaluacion.exigencia == 60
    assert evaluacion.nota_minima == Decimal("1.0")
    assert evaluacion.nota_maxima == Decimal("7.0")
    assert evaluacion.aleatorizar_preguntas is True
    assert evaluacion.aleatorizar_alternativas is True
    assert evaluacion.es_editable


def test_la_ventana_termina_despues_de_empezar():
    evaluacion = crear_evaluacion()
    _rechazada(
        lambda: Evaluacion.objects.filter(pk=evaluacion.pk).update(fin=evaluacion.inicio)
    )


@pytest.mark.parametrize("exigencia", [0, 100])
def test_la_exigencia_queda_entre_1_y_99(exigencia):
    evaluacion = crear_evaluacion()
    _rechazada(lambda: Evaluacion.objects.filter(pk=evaluacion.pk).update(exigencia=exigencia))


@pytest.mark.parametrize(
    ("minima", "maxima"),
    [("0.9", "7.0"), ("4.0", "7.0"), ("1.0", "4.0"), ("1.0", "7.1")],
)
def test_la_escala_de_notas_contiene_al_4(minima, maxima):
    evaluacion = crear_evaluacion()
    _rechazada(
        lambda: Evaluacion.objects.filter(pk=evaluacion.pk).update(
            nota_minima=Decimal(minima), nota_maxima=Decimal(maxima)
        )
    )


def test_una_evaluacion_publicada_tiene_fecha_de_publicacion():
    evaluacion = crear_evaluacion()
    _rechazada(
        lambda: Evaluacion.objects.filter(pk=evaluacion.pk).update(
            estado=EstadoEvaluacion.PUBLICADA
        )
    )


def test_el_estado_es_de_la_lista_cerrada():
    evaluacion = crear_evaluacion()
    _rechazada(lambda: Evaluacion.objects.filter(pk=evaluacion.pk).update(estado="ABIERTA"))


def test_de_una_evaluacion_sale_una_sola_version_nueva():
    original = crear_evaluacion(publicada=True)
    crear_evaluacion(curso=original.curso, evaluacion_origen=original, version=2)
    _rechazada(
        lambda: crear_evaluacion(curso=original.curso, evaluacion_origen=original, version=2)
    )


# --- Preguntas -----------------------------------------------------------------------


@pytest.mark.parametrize("segundos", [10, 300])
def test_el_tiempo_de_10_y_de_300_segundos_se_acepta(segundos):
    evaluacion = crear_evaluacion()
    pregunta = crear_pregunta(evaluacion, orden=1, tiempo_segundos=segundos)
    pregunta.refresh_from_db()
    assert pregunta.tiempo_segundos == segundos


@pytest.mark.parametrize("segundos", [0, 9, 301, 3600])
def test_un_tiempo_fuera_de_10_a_300_segundos_se_rechaza(segundos):
    evaluacion = crear_evaluacion()
    _rechazada(lambda: crear_pregunta(evaluacion, orden=1, tiempo_segundos=segundos))


def test_cambiar_el_tiempo_saltandose_el_modelo_tambien_se_rechaza():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    _rechazada(lambda: Pregunta.objects.filter(pk=pregunta.pk).update(tiempo_segundos=5))


def test_dos_preguntas_no_comparten_orden():
    evaluacion = crear_evaluacion()
    crear_pregunta(evaluacion, orden=1)
    _rechazada(lambda: crear_pregunta(evaluacion, orden=1))


@pytest.mark.parametrize("puntaje", [0, 101])
def test_el_puntaje_va_de_1_a_100(puntaje):
    evaluacion = crear_evaluacion()
    _rechazada(lambda: crear_pregunta(evaluacion, orden=1, puntaje=puntaje))


def test_el_texto_de_la_pregunta_tiene_maximo_1000_caracteres():
    evaluacion = crear_evaluacion()
    crear_pregunta(evaluacion, orden=1, texto="a" * 1000)
    _rechazada(lambda: crear_pregunta(evaluacion, orden=2, texto="a" * 1001), DataError)


def test_la_pregunta_necesita_texto():
    evaluacion = crear_evaluacion()
    _rechazada(lambda: crear_pregunta(evaluacion, orden=1, texto=" \n "))


def test_el_texto_de_la_pregunta_no_aparece_en_su_representacion():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1)
    assert pregunta.texto not in str(pregunta)


# --- Alternativas ----------------------------------------------------------------------


def test_una_pregunta_no_puede_tener_dos_alternativas_correctas():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=3)
    segunda = pregunta.alternativas.get(orden=2)
    _rechazada(lambda: Alternativa.objects.filter(pk=segunda.pk).update(es_correcta=True))


def test_tampoco_se_puede_agregar_una_segunda_correcta():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=2)
    _rechazada(
        lambda: Alternativa.objects.create(
            pregunta=pregunta, orden=3, texto="Otra correcta", es_correcta=True
        )
    )


def test_otra_pregunta_si_puede_tener_su_propia_correcta():
    evaluacion = crear_evaluacion()
    crear_pregunta(evaluacion, orden=1)
    crear_pregunta(evaluacion, orden=2)
    correctas = Alternativa.objects.filter(pregunta__evaluacion=evaluacion, es_correcta=True)
    assert correctas.count() == 2


def test_una_pregunta_no_puede_tener_mas_de_6_alternativas():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=6)
    _rechazada(
        lambda: Alternativa.objects.create(pregunta=pregunta, orden=7, texto="Séptima")
    )
    _rechazada(
        lambda: Alternativa.objects.create(pregunta=pregunta, orden=6, texto="Repite el orden")
    )


def test_el_texto_de_la_alternativa_tiene_maximo_300_caracteres():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=0)
    Alternativa.objects.create(pregunta=pregunta, orden=1, texto="b" * 300)
    _rechazada(
        lambda: Alternativa.objects.create(pregunta=pregunta, orden=2, texto="b" * 301),
        DataError,
    )


# --- Reglas que se revisan al guardar y al publicar --------------------------------------------


def test_una_pregunta_bien_armada_es_valida():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=2)
    validar_pregunta(pregunta)


def test_una_pregunta_con_una_sola_alternativa_no_es_valida():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=1)
    with pytest.raises(ValidationError, match="entre 2 y 6"):
        validar_pregunta(pregunta)


def test_una_pregunta_sin_alternativa_correcta_no_es_valida():
    pregunta = crear_pregunta(crear_evaluacion(), orden=1, alternativas=3)
    pregunta.alternativas.update(es_correcta=False)
    with pytest.raises(ValidationError, match="exactamente una correcta"):
        validar_pregunta(pregunta)


def test_no_se_publica_una_evaluacion_sin_preguntas():
    with pytest.raises(ValidationError, match="al menos una pregunta"):
        validar_para_publicar(crear_evaluacion())


def test_al_publicar_se_informan_todas_las_preguntas_con_problemas():
    evaluacion = crear_evaluacion(preguntas=3)
    evaluacion.preguntas.get(orden=1).alternativas.filter(orden__gt=1).delete()
    evaluacion.preguntas.get(orden=3).alternativas.update(es_correcta=False)
    with pytest.raises(ValidationError) as error:
        validar_para_publicar(evaluacion)
    mensajes = error.value.messages
    assert mensajes == [
        "La pregunta 1 debe tener entre 2 y 6 alternativas.",
        "La pregunta 3 debe tener exactamente una correcta.",
    ]
    # Los mensajes nombran la pregunta por su número, nunca por su texto.
    for pregunta in evaluacion.preguntas.all():
        assert all(pregunta.texto not in mensaje for mensaje in mensajes)


def test_una_evaluacion_completa_se_puede_publicar():
    validar_para_publicar(crear_evaluacion(preguntas=5))


# --- Asignaciones ------------------------------------------------------------------------


def test_la_asignacion_no_tiene_campo_de_motivo():
    # Solo las columnas propias: las relaciones de otros modelos no cuentan.
    campos = {campo.name for campo in AsignacionPrueba._meta.get_fields() if campo.concrete}
    assert campos == {"id", "evaluacion", "alumno", "modalidad", "asignada_por", "asignada_en"}
    prohibidos = ("motivo", "razon", "diagnostico", "observacion", "comentario", "detalle")
    assert not any(palabra in campo for campo in campos for palabra in prohibidos)


def test_la_modalidad_por_omision_es_notia():
    evaluacion = crear_evaluacion()
    asignacion = AsignacionPrueba.objects.create(
        evaluacion=evaluacion, alumno=crear_alumno(), asignada_por=evaluacion.creada_por
    )
    assert asignacion.modalidad == Modalidad.NOTIA


def test_un_alumno_tiene_una_sola_asignacion_por_evaluacion():
    evaluacion, alumno = crear_evaluacion(), crear_alumno()
    asignar(evaluacion, alumno)
    _rechazada(lambda: asignar(evaluacion, alumno, Modalidad.NORMAL))


def test_la_modalidad_es_de_la_lista_cerrada():
    asignacion = asignar(crear_evaluacion(), crear_alumno())
    _rechazada(
        lambda: AsignacionPrueba.objects.filter(pk=asignacion.pk).update(modalidad="ORAL")
    )


def test_borrar_la_evaluacion_borra_sus_preguntas_y_asignaciones():
    evaluacion = crear_evaluacion(preguntas=2)
    asignar(evaluacion, crear_alumno())
    evaluacion.delete()
    assert not Pregunta.objects.exists()
    assert not Alternativa.objects.exists()
    assert not AsignacionPrueba.objects.exists()


def test_un_docente_con_evaluaciones_no_se_borra():
    evaluacion = crear_evaluacion()
    _rechazada(lambda: evaluacion.creada_por.delete(), ProtectedError)

