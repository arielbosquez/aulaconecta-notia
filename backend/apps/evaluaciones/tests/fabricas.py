"""Datos ficticios para las pruebas de evaluaciones, rendición y resultados.

Todos los nombres y correos son de demostración y evidentes. Las funciones
crean lo mínimo y aceptan campos para variar cada caso.
"""

from datetime import timedelta
from itertools import count

from django.utils import timezone

from apps.academico.models import Curso, CursoDocente, Matricula
from apps.cuentas.models import Rol, Usuario
from apps.evaluaciones.models import (
    Alternativa,
    AsignacionPrueba,
    EstadoEvaluacion,
    Evaluacion,
    Modalidad,
    Pregunta,
)

# Contraseña ficticia, solo para las pruebas.
CLAVE = "Ferrocarril-Azul-77"

_numero = count(1)


def crear_usuario(rol: str = Rol.ALUMNO, **campos) -> Usuario:
    n = next(_numero)
    campos.setdefault("nombres", f"Persona{n}")
    campos.setdefault("apellidos", "Demo")
    correo = campos.pop("correo", f"{str(rol).lower()}{n}.demo@aulaconecta.cl")
    if rol == Rol.ALUMNO:
        campos.setdefault("debe_cambiar_password", False)
    return Usuario.objects.create_user(correo, CLAVE, rol=rol, **campos)


def crear_admin(**campos) -> Usuario:
    return crear_usuario(Rol.ADMIN, **campos)


def crear_docente(**campos) -> Usuario:
    return crear_usuario(Rol.DOCENTE, **campos)


def crear_alumno(*, admin: Usuario | None = None, **campos) -> Usuario:
    """Alumno con el consentimiento del apoderado registrado."""
    admin = admin or crear_admin()
    campos.setdefault("consentimiento_verificado_en", timezone.now())
    campos.setdefault("consentimiento_verificado_por", admin)
    return crear_usuario(Rol.ALUMNO, **campos)


def crear_curso(**campos) -> Curso:
    campos.setdefault("nombre", f"2° Medio {next(_numero)}")
    campos.setdefault("anio", 2026)
    return Curso.objects.create(**campos)


def crear_evaluacion(
    *,
    curso: Curso | None = None,
    docente: Usuario | None = None,
    preguntas: int = 0,
    alternativas: int = 4,
    publicada: bool = False,
    **campos,
) -> Evaluacion:
    """Evaluación con ``preguntas`` preguntas de ``alternativas`` alternativas cada una.

    La alternativa correcta de cada pregunta es la primera. Los textos son
    únicos y fáciles de buscar en las respuestas de la API.
    """
    curso = curso or crear_curso()
    docente = docente or crear_docente()
    CursoDocente.objects.get_or_create(curso=curso, docente=docente, asignatura="Ciencias")
    ahora = timezone.now()
    campos.setdefault("titulo", "Prueba de ciencias")
    campos.setdefault("asignatura", "Ciencias")
    campos.setdefault("inicio", ahora - timedelta(hours=1))
    campos.setdefault("fin", ahora + timedelta(hours=2))
    if publicada:
        campos.setdefault("estado", EstadoEvaluacion.PUBLICADA)
        campos.setdefault("publicada_en", ahora - timedelta(hours=1))
    evaluacion = Evaluacion.objects.create(curso=curso, creada_por=docente, **campos)
    for orden in range(1, preguntas + 1):
        crear_pregunta(evaluacion, orden=orden, alternativas=alternativas)
    return evaluacion


def crear_pregunta(
    evaluacion: Evaluacion, *, orden: int, alternativas: int = 4, **campos
) -> Pregunta:
    campos.setdefault("texto", f"Enunciado secreto número {orden} de {evaluacion.id.hex[:8]}")
    campos.setdefault("tiempo_segundos", 60)
    pregunta = Pregunta.objects.create(evaluacion=evaluacion, orden=orden, **campos)
    for letra in range(1, alternativas + 1):
        Alternativa.objects.create(
            pregunta=pregunta,
            orden=letra,
            texto=f"Opción {letra} de la pregunta {orden}",
            es_correcta=letra == 1,
        )
    return pregunta


def asignar(
    evaluacion: Evaluacion, alumno: Usuario, modalidad: str = Modalidad.NOTIA
) -> AsignacionPrueba:
    """Matricula al alumno en el curso de la evaluación y se la asigna."""
    Matricula.objects.get_or_create(curso=evaluacion.curso, alumno=alumno)
    return AsignacionPrueba.objects.create(
        evaluacion=evaluacion,
        alumno=alumno,
        modalidad=modalidad,
        asignada_por=evaluacion.creada_por,
    )
