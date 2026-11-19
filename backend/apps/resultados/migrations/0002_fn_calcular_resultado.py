from django.db import migrations

# Función de corrección (sección 9 de la arquitectura).
#
# - Suma el puntaje de las preguntas no anuladas (total) y el de las
#   respondidas con la alternativa correcta (obtenido).
# - Con exigencia e (60 = 60%) y logro p = obtenido / total:
#     p < e  → nota = mínima + (4 − mínima) × p / e
#     p ≥ e  → nota = 4 + (máxima − 4) × (p − e) / (1 − e)
#   redondeada a un decimal. Se escribe con una sola división (y con la
#   exigencia en porcentaje) para que el resultado sea exacto antes de
#   redondear: así coincide con la implementación de referencia de las pruebas.
# - Sin preguntas válidas (todas anuladas), no hay porcentaje ni nota.
#
# STABLE (solo lee), SECURITY INVOKER (corre con los permisos de quien la
# llama, notia_app), search_path fijo y todas las tablas con su esquema: un
# objeto con el mismo nombre en otro esquema no puede reemplazarlas. Sin SQL
# dinámico. La migración la ejecuta notia_owner, el dueño; notia_app solo
# puede ejecutarla.
CREAR_FUNCION = """
CREATE FUNCTION public.fn_calcular_resultado(p_intento uuid)
RETURNS TABLE (
    puntaje_obtenido numeric,
    puntaje_total numeric,
    porcentaje numeric,
    nota numeric
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $$
    WITH datos AS (
        SELECT
            e.exigencia::numeric AS exigencia,
            e.nota_minima AS minima,
            e.nota_maxima AS maxima,
            COALESCE(SUM(p.puntaje) FILTER (WHERE NOT p.anulada), 0)::numeric AS total,
            COALESCE(
                SUM(p.puntaje) FILTER (WHERE NOT p.anulada AND a.es_correcta), 0
            )::numeric AS obtenido
        FROM public.rendicion_intento AS i
        JOIN public.evaluaciones_evaluacion AS e ON e.id = i.evaluacion_id
        JOIN public.evaluaciones_pregunta AS p ON p.evaluacion_id = e.id
        LEFT JOIN public.rendicion_respuesta AS r
            ON r.intento_id = i.id AND r.pregunta_id = p.id
        LEFT JOIN public.evaluaciones_alternativa AS a
            ON a.id = r.alternativa_id AND a.pregunta_id = p.id
        WHERE i.id = p_intento
        GROUP BY e.id
    )
    SELECT
        obtenido,
        total,
        CASE WHEN total > 0 THEN round(100 * obtenido / total, 2) END,
        CASE
            WHEN total = 0 THEN NULL
            WHEN 100 * obtenido < exigencia * total THEN
                round(minima + (4 - minima) * 100 * obtenido / (exigencia * total), 1)
            ELSE
                round(
                    4 + (maxima - 4) * (100 * obtenido - exigencia * total)
                        / ((100 - exigencia) * total),
                    1
                )
        END
    FROM datos;
$$;

REVOKE ALL ON FUNCTION public.fn_calcular_resultado(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fn_calcular_resultado(uuid) TO notia_app;
"""

BORRAR_FUNCION = "DROP FUNCTION IF EXISTS public.fn_calcular_resultado(uuid);"


class Migration(migrations.Migration):
    dependencies = [
        ("resultados", "0001_initial"),
        ("rendicion", "0001_initial"),
        ("evaluaciones", "0002_asignacion_prueba"),
    ]

    operations = [
        migrations.RunSQL(sql=CREAR_FUNCION, reverse_sql=BORRAR_FUNCION),
    ]
