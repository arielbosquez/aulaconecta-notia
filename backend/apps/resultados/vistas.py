"""Notas publicadas del alumno: ``GET /api/alumno/resultados``."""

from rest_framework.response import Response

from apps.rendicion.vistas import VistaAlumno

from .models import EstadoResultado, Resultado

MAXIMO_RESULTADOS_LISTADOS = 100


def _texto(valor) -> str | None:
    return None if valor is None else str(valor)


class VistaResultadosDelAlumno(VistaAlumno):
    """Solo los resultados que el docente ya publicó (regla 14).

    Un resultado calculado pero no publicado no aparece: ni su nota ni que
    existe. Tampoco se muestra qué preguntas estuvieron buenas o malas.
    """

    def get(self, request):
        resultados = (
            Resultado.objects.filter(
                asignacion__alumno=request.user, estado=EstadoResultado.PUBLICADO
            )
            .select_related("asignacion__evaluacion")
            .order_by("-publicado_en")[:MAXIMO_RESULTADOS_LISTADOS]
        )
        return Response(
            {
                "resultados": [
                    {
                        "evaluacion": {
                            "id": str(resultado.asignacion.evaluacion.id),
                            "titulo": resultado.asignacion.evaluacion.titulo,
                            "asignatura": resultado.asignacion.evaluacion.asignatura,
                        },
                        # Como texto ("6.5"): un decimal exacto, no un número de coma flotante.
                        "nota": _texto(resultado.nota),
                        "porcentaje": _texto(resultado.porcentaje),
                        "publicado_en": resultado.publicado_en,
                    }
                    for resultado in resultados
                ]
            }
        )
