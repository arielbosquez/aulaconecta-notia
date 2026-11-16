"""Revisión estática de backend/db/roles.sql y docker-compose.yml (RS-14 y RS-19).

Los permisos reales de notia_app se prueban contra PostgreSQL cuando existe
la bitácora (Fase 1). Aquí se cuida que los archivos no retrocedan.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
ROLES = (RAIZ / "backend" / "db" / "roles.sql").read_text(encoding="utf-8")
COMPOSE = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")

# El script sin comentarios, en mayúsculas, para revisar solo las sentencias.
SENTENCIAS = "\n".join(
    linea for linea in ROLES.upper().splitlines() if not linea.lstrip().startswith("--")
)


def test_las_contrasenas_vienen_del_entorno_y_no_estan_escritas():
    assert "\\getenv clave_owner DB_OWNER_PASSWORD" in ROLES
    assert "\\getenv clave_app DB_PASSWORD" in ROLES
    # PASSWORD seguido de un literal entre comillas sería una clave en el repositorio.
    assert not re.search(r"PASSWORD\s+'", SENTENCIAS)


def test_ningun_rol_tiene_privilegios_de_administracion():
    creaciones = re.findall(r"CREATE ROLE (NOTIA_\w+) ([A-Z ]+)", SENTENCIAS)
    assert {nombre for nombre, _ in creaciones} == {"NOTIA_OWNER", "NOTIA_APP"}
    for _, atributos in creaciones:
        assert {"NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE"} <= set(atributos.split())


def test_notia_app_solo_recibe_permisos_sobre_filas():
    concedido = " ".join(re.findall(r"GRANT ([^;]+?) TO NOTIA_APP", SENTENCIAS))
    for prohibido in ("ALL", "CREATE", "TRUNCATE", "REFERENCES", "TRIGGER", "TEMP"):
        assert not re.search(
            rf"\b{prohibido}\b(?! ON ALL| TABLES| SEQUENCES| FUNCTIONS)", concedido
        )
    assert "REVOKE ALL ON SCHEMA PUBLIC FROM PUBLIC" in SENTENCIAS


def test_la_bitacora_queda_sin_update_ni_delete():
    assert (
        "REVOKE UPDATE, DELETE, TRUNCATE ON PUBLIC.AUDITORIA_REGISTROAUDITORIA FROM NOTIA_APP"
        in SENTENCIAS
    )


def test_sin_triggers_ni_jobs_en_la_base():
    for prohibido in ("CREATE TRIGGER", "CREATE EVENT TRIGGER", "PG_CRON", "CREATE EXTENSION"):
        assert prohibido not in SENTENCIAS


def test_docker_compose_no_trae_contrasenas_y_solo_escucha_en_local():
    assert "backend/.env" in COMPOSE
    assert not re.search(r"(?im)^\s*[A-Z_]*PASSWORD\s*[:=]", COMPOSE)
    assert '"127.0.0.1:5432:5432"' in COMPOSE
    assert "roles.sql:/docker-entrypoint-initdb.d/" in COMPOSE
