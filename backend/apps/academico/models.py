"""Cursos, docentes por curso y matrículas (sección 6 de la arquitectura).

Estos modelos deciden quién ve qué: un docente solo trabaja con los cursos en
que tiene un ``CursoDocente`` y un alumno solo rinde las pruebas de los cursos
en que tiene una ``Matricula`` activa (sección 10).
"""

import uuid

from django.conf import settings
from django.db import models

# Años en que un curso tiene sentido. Evita un año escrito con un dígito de más.
ANIO_MINIMO = 2020
ANIO_MAXIMO = 2100


class Curso(models.Model):
    """Un curso de un año escolar, por ejemplo "2° Medio A" de 2026."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(max_length=40)
    anio = models.PositiveSmallIntegerField("año")
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "curso"
        verbose_name_plural = "cursos"
        ordering = ["-anio", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["nombre", "anio"], name="curso_unico_por_anio"),
            models.CheckConstraint(
                condition=models.Q(anio__gte=ANIO_MINIMO, anio__lte=ANIO_MAXIMO),
                name="curso_anio_valido",
            ),
            models.CheckConstraint(
                condition=models.Q(nombre__regex=r"\S"), name="curso_nombre_no_vacio"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.anio})"


class CursoDocente(models.Model):
    """Un docente que hace una asignatura en un curso."""

    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, related_name="docentes")
    # PROTECT: un docente con cursos se desactiva, no se borra.
    docente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cursos_que_dicta"
    )
    asignatura = models.CharField(max_length=60)

    class Meta:
        verbose_name = "docente del curso"
        verbose_name_plural = "docentes del curso"
        constraints = [
            models.UniqueConstraint(
                fields=["curso", "docente", "asignatura"], name="curso_docente_unico"
            ),
            models.CheckConstraint(
                condition=models.Q(asignatura__regex=r"\S"),
                name="curso_docente_asignatura_no_vacia",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.docente_id} · {self.asignatura} · {self.curso}"


class Matricula(models.Model):
    """Un alumno inscrito en un curso. Se desactiva en vez de borrarse."""

    curso = models.ForeignKey(Curso, on_delete=models.CASCADE, related_name="matriculas")
    alumno = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="matriculas"
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"
        constraints = [
            models.UniqueConstraint(fields=["curso", "alumno"], name="matricula_unica"),
        ]
        indexes = [models.Index(fields=["alumno", "activa"], name="matricula_por_alumno")]

    def __str__(self) -> str:
        return f"{self.alumno_id} en {self.curso}"

