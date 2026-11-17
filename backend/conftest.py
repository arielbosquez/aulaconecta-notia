"""Preparación de la base de datos de las pruebas.

Las pruebas que usan la base corren contra PostgreSQL real y conectadas como
``notia_app``, el mismo rol de privilegios mínimos que usa la aplicación. Así,
si el código necesita un permiso que la aplicación no tiene (crear una tabla,
modificar la bitácora), la prueba falla igual que fallaría en producción.

``notia_app`` no puede crear bases ni tablas, y ``notia_owner`` tampoco puede
crear bases. Por eso la preparación se reparte entre los tres roles, cada uno
solo para lo suyo:

1. El administrador del servidor (``postgres``, con ``POSTGRES_PASSWORD``)
   crea la base ``test_<nombre>`` con ``notia_owner`` como dueño y le aplica
   ``db/permisos/base_de_datos.sql``, el mismo archivo que usa ``roles.sql``.
2. ``notia_owner`` (con ``DB_OWNER_PASSWORD``) ejecuta las migraciones.
3. ``notia_app`` (con ``DB_PASSWORD``) ejecuta todas las pruebas.

El administrador solo interviene aquí, al crear y al borrar la base de
pruebas: ninguna configuración de Django (``config.settings``) lo conoce.

Las pruebas que no usan la base no necesitan nada de esto y corren aunque
PostgreSQL esté apagado.
"""

import os
from pathlib import Path

import psycopg
import pytest
from django.core.management import call_command
from django.db import connection
from psycopg import sql

ADMINISTRADOR = "postgres"
ROL_DUENO = "notia_owner"
ROL_APLICACION = "notia_app"
PERMISOS = Path(__file__).resolve().parent / "db" / "permisos" / "base_de_datos.sql"


def _variable(nombre: str) -> str:
    """Lee una variable del entorno (``backend/.env`` ya lo cargó la configuración)."""
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        pytest.fail(
            f"Falta la variable de entorno {nombre}: las pruebas que usan la base la "
            "necesitan. En local se define en backend/.env.",
            pytrace=False,
        )
    return valor


def _conectar_como_administrador(base: str) -> psycopg.Connection:
    ajustes = connection.settings_dict
    try:
        return psycopg.connect(
            host=ajustes["HOST"],
            port=ajustes["PORT"],
            dbname=base,
            user=ADMINISTRADOR,
            password=_variable("POSTGRES_PASSWORD"),
            connect_timeout=5,
            autocommit=True,
        )
    except psycopg.OperationalError:
        # No se muestra el error original: puede traer detalles de la conexión.
        pytest.fail(
            "No se pudo conectar a PostgreSQL para preparar la base de pruebas. "
            "Levántalo desde la raíz con: docker compose --env-file backend/.env up -d",
            pytrace=False,
        )


def _borrar_base(nombre: str) -> None:
    with _conectar_como_administrador("postgres") as administrador:
        administrador.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nombre))
        )


def _crear_base(nombre: str) -> None:
    _borrar_base(nombre)
    with _conectar_como_administrador("postgres") as administrador:
        administrador.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(nombre), sql.Identifier(ROL_DUENO)
            )
        )
    with _conectar_como_administrador(nombre) as administrador:
        administrador.execute(PERMISOS.read_text(encoding="utf-8"))


def _usar(nombre: str, rol: str, clave: str) -> None:
    """Hace que la conexión de Django apunte a la base de pruebas con el rol indicado."""
    connection.close()
    connection.settings_dict.update(NAME=nombre, USER=rol, PASSWORD=clave)


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    """Reemplaza la preparación de pytest-django por la de los tres roles."""
    ajustes = connection.settings_dict
    original = {clave: ajustes[clave] for clave in ("NAME", "USER", "PASSWORD")}
    nombre = f"test_{original['NAME']}"
    clave_dueno = _variable("DB_OWNER_PASSWORD")
    clave_aplicacion = _variable("DB_PASSWORD")

    with django_db_blocker.unblock():
        _crear_base(nombre)
        _usar(nombre, ROL_DUENO, clave_dueno)
        call_command("migrate", interactive=False, verbosity=0)
        _usar(nombre, ROL_APLICACION, clave_aplicacion)

    yield

    with django_db_blocker.unblock():
        connection.close()
    ajustes.update(original)
    _borrar_base(nombre)
