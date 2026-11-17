"""Un alumno no ingresa sin el consentimiento del apoderado registrado (RS-17)."""

import pytest
from django.conf import settings
from django.utils import timezone

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.cuentas.models import Usuario

from .conftest import OTRA_CLAVE

pytestmark = pytest.mark.django_db


def test_un_alumno_sin_consentimiento_no_puede_iniciar_sesion(
    navegador, alumno_sin_consentimiento
):
    respuesta = navegador.login(alumno_sin_consentimiento.correo)
    assert respuesta.status_code == 403
    assert respuesta.json() == {
        "codigo": "cuenta_no_habilitada",
        "mensaje": "Tu cuenta aún no está habilitada. Consulta en el colegio.",
    }
    assert settings.COOKIE_ACCESO not in respuesta.cookies
    assert settings.COOKIE_REFRESCO not in respuesta.cookies
    assert navegador.get("/api/auth/yo").status_code == 401


def test_el_rechazo_no_deja_un_acceso_registrado(navegador, alumno_sin_consentimiento):
    navegador.login(alumno_sin_consentimiento.correo)
    assert not RegistroAuditoria.objects.filter(accion=Accion.LOGIN_OK).exists()
    alumno_sin_consentimiento.refresh_from_db()
    assert alumno_sin_consentimiento.ultimo_acceso is None


def test_sin_la_contrasena_correcta_no_se_revela_que_falta_el_consentimiento(
    navegador, alumno_sin_consentimiento
):
    respuesta = navegador.login(alumno_sin_consentimiento.correo, OTRA_CLAVE)
    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "credenciales_invalidas"


def test_el_alumno_ingresa_cuando_el_administrador_registra_el_consentimiento(
    navegador, alumno_sin_consentimiento, admin
):
    assert navegador.login(alumno_sin_consentimiento.correo).status_code == 403
    Usuario.objects.filter(pk=alumno_sin_consentimiento.pk).update(
        consentimiento_verificado_en=timezone.now(), consentimiento_verificado_por=admin
    )
    respuesta = navegador.login(alumno_sin_consentimiento.correo)
    assert respuesta.status_code == 200
    assert respuesta.json()["paso"] == "listo"


def test_el_consentimiento_no_se_exige_a_docentes_ni_administradores(navegador, docente, admin):
    # No son menores a cargo del colegio: su ingreso depende del segundo factor.
    for persona in (docente, admin):
        respuesta = navegador.login(persona.correo)
        assert respuesta.status_code == 200
        assert respuesta.json()["paso"] == "enrolar_mfa"
