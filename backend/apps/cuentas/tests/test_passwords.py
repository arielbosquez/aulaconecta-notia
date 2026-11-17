"""Pruebas del hasher y de la política de contraseñas por rol (RS-01)."""

import pytest
from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ImproperlyConfigured, ValidationError

from apps.cuentas.models import Rol, Usuario
from config import entorno

# Contraseñas ficticias, solo para estas pruebas.
CLAVE_DE_10 = "Ferrocarri"
CLAVE_DE_12 = "Ferrocarril7"


def _usuario(rol: str) -> Usuario:
    return Usuario(
        correo="persona.demo@aulaconecta.cl", nombres="Persona", apellidos="Demo", rol=rol
    )


def _codigos(clave: str, usuario=None) -> set[str]:
    try:
        validate_password(clave, usuario)
    except ValidationError as error:
        return {detalle.code for detalle in error.error_list}
    return set()


def test_argon2id_es_el_unico_hasher():
    assert settings.PASSWORD_HASHERS == ["django.contrib.auth.hashers.Argon2PasswordHasher"]
    guardado = make_password(CLAVE_DE_12)
    assert guardado.startswith("argon2$argon2id$")
    assert identify_hasher(guardado).algorithm == "argon2"
    assert CLAVE_DE_12 not in guardado
    assert check_password(CLAVE_DE_12, guardado)
    assert not check_password(CLAVE_DE_10, guardado)


def test_dos_hashes_de_la_misma_contrasena_son_distintos():
    assert make_password(CLAVE_DE_12) != make_password(CLAVE_DE_12)


def test_un_hash_de_otro_algoritmo_no_se_acepta():
    # Formatos de otros algoritmos con datos ficticios: ningún hasher los reconoce.
    assert not check_password(CLAVE_DE_12, "pbkdf2_sha256$1000000$sal$ZmljdGljaW8=")
    assert not check_password(CLAVE_DE_12, "md5$sal$0123456789abcdef0123456789abcdef")


def test_set_password_del_usuario_usa_argon2id():
    usuario = _usuario(Rol.ALUMNO)
    usuario.set_password(CLAVE_DE_10)
    assert usuario.password.startswith("argon2$argon2id$")


def test_los_largos_minimos_son_los_de_la_arquitectura():
    assert settings.PASSWORD_LARGO_MINIMO_ALUMNO == 10
    assert settings.PASSWORD_LARGO_MINIMO_PERSONAL == 12


def test_un_alumno_necesita_al_menos_10_caracteres():
    alumno = _usuario(Rol.ALUMNO)
    assert "password_muy_corta" in _codigos(CLAVE_DE_10[:9], alumno)
    assert _codigos(CLAVE_DE_10, alumno) == set()


@pytest.mark.parametrize("rol", [Rol.DOCENTE, Rol.ADMIN])
def test_el_personal_necesita_al_menos_12_caracteres(rol):
    persona = _usuario(rol)
    assert "password_muy_corta" in _codigos(CLAVE_DE_10, persona)
    assert "password_muy_corta" in _codigos(CLAVE_DE_12[:11], persona)
    assert _codigos(CLAVE_DE_12, persona) == set()


def test_sin_usuario_se_aplica_el_largo_mas_exigente():
    assert "password_muy_corta" in _codigos(CLAVE_DE_10)
    assert _codigos(CLAVE_DE_12) == set()


def test_el_mensaje_indica_el_largo_exigido():
    with pytest.raises(ValidationError) as error:
        validate_password("corta", _usuario(Rol.DOCENTE))
    assert "al menos 12 caracteres" in " ".join(error.value.messages)


def test_se_rechazan_contrasenas_comunes_numericas_o_parecidas_a_los_datos():
    alumno = _usuario(Rol.ALUMNO)
    assert "password_too_common" in _codigos("password1234", alumno)
    assert "password_entirely_numeric" in _codigos("73920184650913", alumno)
    assert "password_too_similar" in _codigos("persona.demo@aulaconecta.cl", alumno)


def test_el_largo_minimo_se_puede_subir_pero_no_bajar(monkeypatch):
    monkeypatch.setenv("PASSWORD_LARGO_MINIMO_ALUMNO", "14")
    assert entorno.leer_entero("PASSWORD_LARGO_MINIMO_ALUMNO", defecto=10, minimo=10) == 14
    for invalido in ("8", "diez", "10.5"):
        monkeypatch.setenv("PASSWORD_LARGO_MINIMO_ALUMNO", invalido)
        with pytest.raises(ImproperlyConfigured, match="PASSWORD_LARGO_MINIMO_ALUMNO"):
            entorno.leer_entero("PASSWORD_LARGO_MINIMO_ALUMNO", defecto=10, minimo=10)


def test_leer_entero_respeta_el_maximo_y_el_valor_por_omision(monkeypatch):
    monkeypatch.delenv("NOTIA_PRUEBA", raising=False)
    assert entorno.leer_entero("NOTIA_PRUEBA", defecto=3) == 3
    monkeypatch.setenv("NOTIA_PRUEBA", "9")
    with pytest.raises(ImproperlyConfigured, match="entre 0 y 5"):
        entorno.leer_entero("NOTIA_PRUEBA", defecto=3, maximo=5)
