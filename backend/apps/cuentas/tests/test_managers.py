"""Pruebas del manager de Usuario que no necesitan base de datos.

El guardado se reemplaza por una función que solo anota la llamada: aquí se
comprueba lo que el manager decide antes de guardar (correo normalizado,
contraseña como hash y marca de superusuario), no la escritura en PostgreSQL.
"""

import pytest
from django.contrib.auth.base_user import AbstractBaseUser

from apps.cuentas.managers import UsuarioManager
from apps.cuentas.models import Usuario

CORREO = "docente.demo@aulaconecta.cl"
CLAVE = "clave-ficticia-de-prueba"


@pytest.fixture
def guardados(monkeypatch):
    """Evita la escritura en la base y entrega la lista de usuarios guardados."""
    registro = []

    def anotar(self, *args, **kwargs):
        registro.append(self)

    monkeypatch.setattr(AbstractBaseUser, "save", anotar)
    return registro


def test_create_user_normaliza_el_correo_y_guarda_el_hash(guardados):
    usuario = Usuario.objects.create_user(
        "  Docente.Demo@AulaConecta.CL ", CLAVE, nombres="Docente", apellidos="Demo"
    )
    assert guardados == [usuario]
    assert usuario.correo == CORREO
    assert CLAVE not in usuario.password
    assert usuario.check_password(CLAVE)


def test_create_user_nunca_crea_un_superusuario(guardados):
    usuario = Usuario.objects.create_user(CORREO, CLAVE, is_superuser=True)
    assert usuario.is_superuser is False


def test_create_user_sin_contrasena_deja_la_cuenta_sin_clave_utilizable(guardados):
    usuario = Usuario.objects.create_user(CORREO)
    assert not usuario.has_usable_password()


@pytest.mark.parametrize("correo", ["", "   ", None])
def test_create_user_exige_correo(guardados, correo):
    with pytest.raises(ValueError, match="correo"):
        Usuario.objects.create_user(correo, CLAVE)
    assert guardados == []


def test_create_superuser_marca_al_usuario_como_superusuario(guardados):
    usuario = Usuario.objects.create_superuser(CORREO, CLAVE)
    assert usuario.is_superuser is True
    assert usuario.check_password(CLAVE)


@pytest.mark.parametrize("clave", ["", None])
def test_create_superuser_exige_contrasena(guardados, clave):
    with pytest.raises(ValueError, match="contraseña"):
        Usuario.objects.create_superuser(CORREO, clave)
    assert guardados == []


def test_get_by_natural_key_busca_con_el_correo_normalizado(monkeypatch):
    busquedas = []

    def anotar(self, **filtros):
        busquedas.append(filtros)

    monkeypatch.setattr(UsuarioManager, "get", anotar)
    Usuario.objects.get_by_natural_key(" Docente.Demo@AulaConecta.CL")
    assert busquedas == [{"correo": CORREO}]


def test_guardar_un_usuario_normaliza_su_correo(guardados):
    usuario = Usuario(correo=" Alumno.Demo@AulaConecta.CL ", nombres="Alumno", apellidos="Demo")
    usuario.save()
    assert usuario.correo == "alumno.demo@aulaconecta.cl"
    assert guardados == [usuario]


def test_el_usuario_se_muestra_con_su_nombre_completo():
    usuario = Usuario(correo="alumno.demo@aulaconecta.cl", nombres="Alumno", apellidos="Demo")
    assert str(usuario) == "Alumno Demo"
