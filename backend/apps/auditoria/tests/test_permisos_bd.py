"""La bitácora es de solo inserción también en PostgreSQL (RS-16).

Estas pruebas no confían en el modelo: se conectan como ``notia_app``, el rol
de la aplicación, y le piden a PostgreSQL con SQL directo que modifique o
borre registros. Quien rechaza es la base de datos, así que la barrera sigue
en pie aunque alguien se salte el código de Django.

Corren contra PostgreSQL real, en local y en el CI (ver ``backend/conftest.py``).
"""

import pytest
from django.db import ProgrammingError, connection, transaction
from psycopg import errors

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.auditoria.servicios import registrar

pytestmark = pytest.mark.django_db

# El nombre de la tabla va escrito en cada sentencia, sin armar SQL con cadenas.
TABLA = "auditoria_registroauditoria"


def test_el_nombre_de_la_tabla_es_el_que_usan_las_sentencias():
    assert RegistroAuditoria._meta.db_table == TABLA


@pytest.fixture
def registro():
    return registrar(Accion.LOGIN_OK, detalle={"origen": "prueba"})


def _privilegio(nombre: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user, %s, %s)", [TABLA, nombre])
        return cursor.fetchone()[0]


def _rechazada_por_la_base(sentencia: str, parametros=None) -> None:
    """Ejecuta SQL directo y exige que PostgreSQL lo rechace por falta de privilegios."""
    with pytest.raises(ProgrammingError) as rechazo, transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(sentencia, parametros)
    assert isinstance(rechazo.value.__cause__, errors.InsufficientPrivilege)


def test_la_prueba_se_conecta_con_el_rol_de_la_aplicacion():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, session_user")
        assert cursor.fetchone() == ("notia_app", "notia_app")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        assert cursor.fetchone() == (False,)
        cursor.execute("SELECT tableowner FROM pg_tables WHERE tablename = %s", [TABLA])
        assert cursor.fetchone() == ("notia_owner",)


def test_notia_app_solo_tiene_select_e_insert_sobre_la_bitacora():
    assert _privilegio("SELECT") is True
    assert _privilegio("INSERT") is True
    for prohibido in ("UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert _privilegio(prohibido) is False, prohibido


def test_notia_app_inserta_y_lee(registro):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT accion, detalle->>'origen' FROM auditoria_registroauditoria WHERE id = %s",
            [registro.pk],
        )
        assert cursor.fetchone() == ("LOGIN_OK", "prueba")


def test_postgresql_rechaza_el_update(registro):
    _rechazada_por_la_base(
        "UPDATE auditoria_registroauditoria SET accion = %s WHERE id = %s",
        [Accion.LOGOUT, registro.pk],
    )
    assert RegistroAuditoria.objects.get(pk=registro.pk).accion == Accion.LOGIN_OK


def test_postgresql_rechaza_el_update_de_una_sola_columna(registro):
    # Tampoco hay permisos por columna que dejen una rendija.
    for sentencia in (
        "UPDATE auditoria_registroauditoria SET detalle = '{}' WHERE id = %s",
        "UPDATE auditoria_registroauditoria SET actor_id = NULL WHERE id = %s",
        "UPDATE auditoria_registroauditoria SET ip = NULL WHERE id = %s",
        "UPDATE auditoria_registroauditoria SET ocurrido_en = now() WHERE id = %s",
    ):
        _rechazada_por_la_base(sentencia, [registro.pk])


def test_postgresql_rechaza_el_delete(registro):
    _rechazada_por_la_base("DELETE FROM auditoria_registroauditoria WHERE id = %s", [registro.pk])
    _rechazada_por_la_base("DELETE FROM auditoria_registroauditoria")
    assert RegistroAuditoria.objects.filter(pk=registro.pk).exists()


def test_postgresql_rechaza_el_truncate(registro):
    _rechazada_por_la_base("TRUNCATE auditoria_registroauditoria")
    assert RegistroAuditoria.objects.filter(pk=registro.pk).exists()


def test_postgresql_rechaza_un_insert_que_pisa_un_registro(registro):
    # INSERT ... ON CONFLICT DO UPDATE necesita UPDATE: no sirve como atajo.
    _rechazada_por_la_base(
        "INSERT INTO auditoria_registroauditoria "
        "(id, ocurrido_en, rol_actor, accion, objeto_tipo, objeto_id, user_agent, detalle) "
        "VALUES (%s, now(), '', %s, '', '', '', '{}') "
        "ON CONFLICT (id) DO UPDATE SET accion = EXCLUDED.accion",
        [registro.pk, Accion.LOGOUT],
    )
    assert RegistroAuditoria.objects.get(pk=registro.pk).accion == Accion.LOGIN_OK


def test_postgresql_rechaza_tambien_al_orm_sin_las_protecciones_del_modelo(registro):
    # _base_manager entrega consultas sin las protecciones del modelo; la base no cede.
    consulta = RegistroAuditoria._base_manager.filter(pk=registro.pk)
    with pytest.raises(ProgrammingError), transaction.atomic():
        consulta.update(accion=Accion.LOGOUT)
    with pytest.raises(ProgrammingError), transaction.atomic():
        consulta._raw_delete(consulta.db)
    assert RegistroAuditoria.objects.get(pk=registro.pk).accion == Accion.LOGIN_OK


def test_notia_app_no_puede_devolverse_los_permisos():
    # Un GRANT de quien no es dueño no da error: PostgreSQL solo avisa y no
    # concede nada. Por eso se comprueba el resultado y no una excepción.
    with connection.cursor() as cursor:
        cursor.execute("GRANT UPDATE, DELETE ON auditoria_registroauditoria TO notia_app")
    assert _privilegio("UPDATE") is False
    assert _privilegio("DELETE") is False

    _rechazada_por_la_base("ALTER TABLE auditoria_registroauditoria OWNER TO notia_app")
    _rechazada_por_la_base("SET ROLE notia_owner")
