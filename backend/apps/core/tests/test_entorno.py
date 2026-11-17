"""Pruebas de la lectura de configuración desde variables de entorno (RS-14)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core.llaves import (
    es_llave_fernet,
    nueva_llave_fernet,
    nueva_llave_secreta,
    validar_llaves,
)
from config import entorno

BACKEND = Path(__file__).resolve().parents[3]

# Variables que la configuración de producción exige para arrancar.
OBLIGATORIAS_EN_PRODUCCION = (
    "DJANGO_SECRET_KEY",
    "JWT_SIGNING_KEY",
    "MFA_ENCRYPTION_KEY",
    "ALLOWED_HOSTS",
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "AZURE_STORAGE_ACCOUNT_NAME",
    "AZURE_STORAGE_CONTAINER",
)


@pytest.fixture
def en_produccion(monkeypatch):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")


@pytest.fixture
def en_desarrollo(monkeypatch):
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.dev")


def test_solo_dev_y_test_son_entornos_locales(monkeypatch):
    for modulo, esperado in [
        ("config.settings.dev", False),
        ("config.settings.test", False),
        ("config.settings.prod", True),
        ("config.settings.otro", True),
        ("", True),
    ]:
        monkeypatch.setenv("DJANGO_SETTINGS_MODULE", modulo)
        assert entorno.es_produccion() is esperado


def test_variable_obligatoria_faltante_detiene_produccion(monkeypatch, en_produccion):
    monkeypatch.delenv("NOTIA_PRUEBA", raising=False)
    with pytest.raises(ImproperlyConfigured, match="NOTIA_PRUEBA"):
        entorno.leer("NOTIA_PRUEBA", defecto="no-debe-usarse", obligatoria=True)


def test_variable_obligatoria_vacia_cuenta_como_faltante(monkeypatch, en_produccion):
    monkeypatch.setenv("NOTIA_PRUEBA", "   ")
    with pytest.raises(ImproperlyConfigured):
        entorno.leer("NOTIA_PRUEBA", obligatoria=True)


def test_fuera_de_produccion_se_usa_el_valor_por_omision(monkeypatch, en_desarrollo):
    monkeypatch.delenv("NOTIA_PRUEBA", raising=False)
    assert entorno.leer("NOTIA_PRUEBA", defecto="local", obligatoria=True) == "local"


def test_variable_opcional_faltante_no_falla_en_produccion(monkeypatch, en_produccion):
    monkeypatch.delenv("NOTIA_PRUEBA", raising=False)
    assert entorno.leer("NOTIA_PRUEBA") == ""


def test_el_error_no_muestra_valores(monkeypatch, en_produccion):
    monkeypatch.setenv("NOTIA_PRUEBA", "valor-reservado")
    with pytest.raises(ImproperlyConfigured) as error:
        entorno.leer_opcion("NOTIA_PRUEBA", opciones=("a", "b"), defecto="a")
    assert "valor-reservado" not in str(error.value)


def test_leer_lista_separa_por_coma_y_descarta_vacios(monkeypatch, en_desarrollo):
    monkeypatch.setenv("NOTIA_PRUEBA", " uno, dos ,,tres ")
    assert entorno.leer_lista("NOTIA_PRUEBA") == ["uno", "dos", "tres"]
    monkeypatch.delenv("NOTIA_PRUEBA")
    assert entorno.leer_lista("NOTIA_PRUEBA", defecto=("x",)) == ["x"]


def test_leer_opcion_rechaza_valores_fuera_de_la_lista(monkeypatch, en_desarrollo):
    monkeypatch.setenv("NOTIA_PRUEBA", "AZURE")
    assert entorno.leer_opcion("NOTIA_PRUEBA", opciones=("azure", "prueba"), defecto="prueba") == (
        "azure"
    )
    monkeypatch.setenv("NOTIA_PRUEBA", "otro")
    with pytest.raises(ImproperlyConfigured, match="NOTIA_PRUEBA"):
        entorno.leer_opcion("NOTIA_PRUEBA", opciones=("azure", "prueba"), defecto="prueba")


def test_cargar_archivo_env_no_pisa_el_entorno(monkeypatch, tmp_path):
    archivo = tmp_path / ".env"
    archivo.write_text(
        "# comentario\n\nNOTIA_A=desde-archivo\nNOTIA_B = 'con comillas'\nlinea sin igual\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NOTIA_A", "desde-entorno")
    monkeypatch.delenv("NOTIA_B", raising=False)
    entorno.cargar_archivo_env(archivo)
    try:
        assert os.environ["NOTIA_A"] == "desde-entorno"
        assert os.environ["NOTIA_B"] == "con comillas"
    finally:
        os.environ.pop("NOTIA_B", None)


def test_cargar_archivo_env_inexistente_no_falla(tmp_path):
    entorno.cargar_archivo_env(tmp_path / "no-existe.env")


def test_las_llaves_generadas_son_validas_y_distintas():
    secreta, jwt, mfa = nueva_llave_secreta(), nueva_llave_secreta(), nueva_llave_fernet()
    assert es_llave_fernet(mfa)
    assert not es_llave_fernet(secreta)
    validar_llaves(secreta=secreta, jwt=jwt, mfa=mfa)


def test_validar_llaves_rechaza_llaves_debiles_o_repetidas():
    secreta, mfa = nueva_llave_secreta(), nueva_llave_fernet()
    with pytest.raises(ImproperlyConfigured, match="distintas"):
        validar_llaves(secreta=secreta, jwt=secreta, mfa=mfa)
    with pytest.raises(ImproperlyConfigured, match="JWT_SIGNING_KEY"):
        validar_llaves(secreta=secreta, jwt="corta", mfa=mfa)
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        validar_llaves(secreta="a" * 60, jwt=nueva_llave_secreta(), mfa=mfa)
    with pytest.raises(ImproperlyConfigured, match="MFA_ENCRYPTION_KEY"):
        validar_llaves(secreta=secreta, jwt=nueva_llave_secreta(), mfa="no-es-fernet")


def _entorno_de_produccion() -> dict[str, str]:
    """Entorno mínimo y ficticio para arrancar con la configuración de producción."""
    variables = {
        nombre: valor
        for nombre, valor in os.environ.items()
        if not nombre.startswith(("DJANGO_", "DB_", "JWT_", "MFA_", "AZURE_"))
        and nombre not in {"ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "PROVEEDOR_VOZ"}
    }
    variables.update(
        DJANGO_SETTINGS_MODULE="config.settings.prod",
        DJANGO_SECRET_KEY=nueva_llave_secreta(),
        JWT_SIGNING_KEY=nueva_llave_secreta(),
        MFA_ENCRYPTION_KEY=nueva_llave_fernet(),
        ALLOWED_HOSTS="notia.example",
        DB_HOST="bd.example",
        DB_NAME="notia",
        DB_USER="notia_app",
        DB_PASSWORD=nueva_llave_secreta(),
        AZURE_STORAGE_ACCOUNT_NAME="cuentaficticia",
        AZURE_STORAGE_CONTAINER="privado",
    )
    return variables


def _check_deploy(variables: dict[str, str]) -> subprocess.CompletedProcess:
    # Se ejecuta el mismo intérprete de las pruebas con argumentos fijos.
    return subprocess.run(  # noqa: S603
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
        cwd=BACKEND,
        env=variables,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_produccion_completa_pasa_check_deploy_sin_advertencias():
    resultado = _check_deploy(_entorno_de_produccion())
    assert resultado.returncode == 0, resultado.stderr
    assert "no issues" in resultado.stdout


@pytest.mark.parametrize("faltante", OBLIGATORIAS_EN_PRODUCCION)
def test_produccion_no_arranca_si_falta_una_variable(faltante):
    variables = _entorno_de_produccion()
    del variables[faltante]
    resultado = _check_deploy(variables)
    assert resultado.returncode != 0
    assert f"obligatoria {faltante}" in resultado.stderr


def test_produccion_exige_conexion_cifrada_a_la_base():
    variables = _entorno_de_produccion()
    variables["DB_SSLMODE"] = "prefer"
    resultado = _check_deploy(variables)
    assert resultado.returncode != 0
    assert "DB_SSLMODE" in resultado.stderr


def ajustes_de_produccion(nombres: list[str], **variables_extra: str) -> list[str]:
    """Arranca Django con la configuración de producción y devuelve esos ajustes."""
    variables = _entorno_de_produccion()
    variables.update(variables_extra)
    programa = (
        "import sys; from django.conf import settings; "
        "print('\\n'.join(str(getattr(settings, nombre)) for nombre in sys.argv[1:]))"
    )
    resultado = subprocess.run(  # noqa: S603
        [sys.executable, "-c", programa, *nombres],
        cwd=BACKEND,
        env=variables,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    return resultado.stdout.split()


def test_produccion_confia_en_un_solo_proxy_y_se_puede_configurar():
    # Azure App Service pone un proxy delante de la aplicación.
    assert ajustes_de_produccion(["PROXIES_DE_CONFIANZA"]) == ["1"]
    assert ajustes_de_produccion(["PROXIES_DE_CONFIANZA"], PROXIES_DE_CONFIANZA="2") == ["2"]


def test_el_numero_de_proxies_debe_ser_un_entero_razonable():
    variables = _entorno_de_produccion()
    variables["PROXIES_DE_CONFIANZA"] = "muchos"
    resultado = _check_deploy(variables)
    assert resultado.returncode != 0
    assert "PROXIES_DE_CONFIANZA" in resultado.stderr
