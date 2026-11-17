"""Ayudantes compartidos por las pruebas de autenticación."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cuentas.models import Rol, Usuario

# Contraseñas ficticias, solo para las pruebas.
CLAVE = "Ferrocarril-Azul-77"
OTRA_CLAVE = "Cordillera-Verde-42"


class Navegador(APIClient):
    """Cliente que se comporta como un navegador real frente al CSRF.

    Exige el token CSRF (el cliente de pruebas de Django lo omite por omisión)
    y lo envía en ``X-CSRFToken`` leyéndolo de la cookie, como hará el frontend.
    """

    def __init__(self):
        super().__init__(enforce_csrf_checks=True)

    def pedir_csrf(self) -> str:
        respuesta = self.get("/api/auth/csrf")
        assert respuesta.status_code == 204
        return self.cookies["csrftoken"].value

    def enviar(self, ruta: str, datos=None, *, con_csrf: bool = True, **extra):
        if con_csrf:
            if "csrftoken" not in self.cookies:
                self.pedir_csrf()
            extra.setdefault("HTTP_X_CSRFTOKEN", self.cookies["csrftoken"].value)
        return self.post(ruta, datos or {}, format="json", **extra)

    def login(self, correo: str, password: str = CLAVE, **extra):
        return self.enviar("/api/auth/login", {"correo": correo, "password": password}, **extra)


@pytest.fixture
def navegador():
    return Navegador()


def crear_usuario(correo: str, rol: str = Rol.ALUMNO, *, password: str = CLAVE, **campos):
    campos.setdefault("nombres", "Persona")
    campos.setdefault("apellidos", "Demo")
    return Usuario.objects.create_user(correo, password, rol=rol, **campos)


@pytest.fixture
def admin(db):
    return crear_usuario("admin.demo@aulaconecta.cl", Rol.ADMIN, nombres="Admin")


@pytest.fixture
def docente(db):
    return crear_usuario("docente.demo@aulaconecta.cl", Rol.DOCENTE, nombres="Docente")


@pytest.fixture
def alumno(db, admin):
    """Alumno con el consentimiento del apoderado ya registrado."""
    return crear_usuario(
        "alumno.demo@aulaconecta.cl",
        nombres="Alumno",
        debe_cambiar_password=False,
        consentimiento_verificado_en=timezone.now(),
        consentimiento_verificado_por=admin,
    )


@pytest.fixture
def alumno_sin_consentimiento(db):
    return crear_usuario("alumna.demo@aulaconecta.cl", nombres="Alumna")
