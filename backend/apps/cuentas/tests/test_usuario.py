"""Pruebas del modelo Usuario que no necesitan base de datos."""

import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.cuentas.managers import normalizar_correo
from apps.cuentas.models import Usuario


def test_usuario_es_el_modelo_de_autenticacion():
    assert settings.AUTH_USER_MODEL == "cuentas.Usuario"
    assert get_user_model() is Usuario


def test_el_admin_de_django_no_esta_instalado():
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


def test_se_identifica_por_correo_y_usa_uuid():
    usuario = Usuario(correo="alumno.demo@aulaconecta.cl", nombres="Alumno", apellidos="Demo")
    assert Usuario.USERNAME_FIELD == "correo"
    assert isinstance(usuario.id, uuid.UUID)
    assert usuario.nombre_completo == "Alumno Demo"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Alumno.Demo@AulaConecta.CL", "alumno.demo@aulaconecta.cl"),
        ("  docente.demo@aulaconecta.cl ", "docente.demo@aulaconecta.cl"),
        ("", ""),
    ],
)
def test_normalizar_correo(entrada, esperado):
    assert normalizar_correo(entrada) == esperado


def test_la_contrasena_se_guarda_como_hash():
    usuario = Usuario(correo="alumno.demo@aulaconecta.cl")
    usuario.set_password("clave-ficticia-de-prueba")
    assert "clave-ficticia-de-prueba" not in usuario.password
    assert usuario.check_password("clave-ficticia-de-prueba")


def test_no_guarda_datos_personales_innecesarios():
    campos = {campo.name for campo in Usuario._meta.get_fields()}
    prohibidos = {"rut", "fecha_nacimiento", "direccion", "telefono"}
    assert campos.isdisjoint(prohibidos)
