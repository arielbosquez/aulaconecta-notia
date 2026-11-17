"""Privilegios mínimos comprobados contra PostgreSQL real (RS-19).

Estas pruebas se conectan como ``notia_app`` a una base preparada con
``db/permisos/base_de_datos.sql`` (ver ``backend/conftest.py``) e intentan
hacer lo que la aplicación nunca debe poder hacer.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import ProgrammingError, connection, transaction
from psycopg import errors

pytestmark = pytest.mark.django_db


def _consultar(consulta: str):
    with connection.cursor() as cursor:
        cursor.execute(consulta)
        return cursor.fetchone()


def _ejecutar_esperando_rechazo(sentencia: str) -> None:
    """Ejecuta la sentencia y exige que PostgreSQL la rechace por falta de privilegios."""
    with pytest.raises(ProgrammingError) as rechazo, transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sentencia)
    assert isinstance(rechazo.value.__cause__, errors.InsufficientPrivilege)


def test_las_pruebas_corren_con_el_rol_de_la_aplicacion():
    usuario, base = _consultar("SELECT current_user, current_database()")
    assert usuario == "notia_app"
    assert base.startswith("test_")


def test_el_rol_de_la_aplicacion_no_tiene_atributos_de_administracion():
    atributos = _consultar(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    )
    assert atributos == (False, False, False, False, False)


def test_el_rol_de_la_aplicacion_no_es_dueno_de_ninguna_tabla():
    (propias,) = _consultar(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user"
    )
    (del_dueno,) = _consultar(
        "SELECT count(*) FROM pg_tables "
        "WHERE schemaname = 'public' AND tableowner = 'notia_owner'"
    )
    assert propias == 0
    assert del_dueno > 0


def test_la_aplicacion_lee_y_escribe_filas():
    Usuario = get_user_model()
    usuario = Usuario.objects.create_user(
        "alumno.demo@aulaconecta.cl", nombres="Alumno", apellidos="Demo"
    )
    usuario.nombres = "Alumna"
    usuario.save(update_fields=["nombres"])
    assert Usuario.objects.get(correo="alumno.demo@aulaconecta.cl").nombres == "Alumna"
    usuario.delete()
    assert not Usuario.objects.exists()


@pytest.mark.parametrize(
    "sentencia",
    [
        "CREATE TABLE prueba_privilegios (id integer)",
        "CREATE SCHEMA prueba_privilegios",
        "DROP TABLE cuentas_usuario",
        "ALTER TABLE cuentas_usuario ADD COLUMN rut text",
        "TRUNCATE cuentas_usuario CASCADE",
        "CREATE INDEX prueba_privilegios ON cuentas_usuario (nombres)",
    ],
)
def test_la_aplicacion_no_puede_cambiar_la_estructura(sentencia):
    _ejecutar_esperando_rechazo(sentencia)


def test_la_aplicacion_no_puede_crear_bases_ni_roles():
    # CREATE DATABASE no admite transacción; basta con mirar el privilegio.
    (puede_crear_en_la_base,) = _consultar(
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
    )
    assert puede_crear_en_la_base is False
    _ejecutar_esperando_rechazo("CREATE ROLE prueba_privilegios")


def test_otros_roles_no_entran_por_el_esquema_publico():
    (publico_puede_crear,) = _consultar(
        "SELECT has_schema_privilege('public', 'public', 'CREATE')"
    )
    (publico_puede_conectar,) = _consultar(
        "SELECT has_database_privilege('public', current_database(), 'CONNECT')"
    )
    assert publico_puede_crear is False
    assert publico_puede_conectar is False
