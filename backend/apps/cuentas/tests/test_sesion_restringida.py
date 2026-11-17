"""Docentes y administradores no obtienen una sesión completa solo con la contraseña (RS-06).

El segundo factor llega en el PR 1.5. Mientras tanto no hay atajo: tras la
contraseña, el personal queda con una sesión restringida a enrolar el 2FA (si
aún no lo activa) o sin sesión alguna (si ya lo tiene y debe verificarlo).
"""

import pytest
from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.cuentas.models import Rol, Usuario
from apps.cuentas.permisos import SesionCompleta
from apps.cuentas.tokens import (
    CLAIM_ALCANCE,
    CLAIM_VERSION,
    Alcance,
    alcance_tras_la_contrasena,
    emitir_tokens,
)

from .conftest import Navegador

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.cuentas.tests.urls_sesion")]

ACCESO = settings.COOKIE_ACCESO
REFRESCO = settings.COOKIE_REFRESCO


def _con_tokens(usuario, alcance) -> Navegador:
    """Navegador con las cookies de una sesión emitida directamente con ese alcance."""
    navegador = Navegador()
    tokens = emitir_tokens(usuario, alcance)
    navegador.cookies[ACCESO] = tokens.acceso
    navegador.cookies[REFRESCO] = tokens.refresco
    return navegador


def test_el_permiso_por_omision_de_la_api_es_sesion_completa():
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "apps.cuentas.permisos.SesionCompleta"
    ]
    assert SesionCompleta.__module__ == "apps.cuentas.permisos"


def test_solo_un_alumno_obtiene_sesion_completa_con_la_contrasena():
    assert alcance_tras_la_contrasena(Usuario(rol=Rol.ALUMNO)) is Alcance.COMPLETA
    for rol in (Rol.DOCENTE, Rol.ADMIN):
        assert alcance_tras_la_contrasena(Usuario(rol=rol)) is Alcance.ENROLAR_MFA
        assert alcance_tras_la_contrasena(Usuario(rol=rol, mfa_habilitado=True)) is None


# --- Personal sin 2FA activado: sesión restringida ---------------------------


@pytest.mark.parametrize("persona", ["docente", "admin"])
def test_el_personal_sin_2fa_queda_en_el_paso_de_enrolar(navegador, persona, request):
    usuario = request.getfixturevalue(persona)
    respuesta = navegador.login(usuario.correo)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"paso": "enrolar_mfa"}
    assert AccessToken(respuesta.cookies[ACCESO].value)[CLAIM_ALCANCE] == "enrolar_mfa"
    assert RefreshToken(respuesta.cookies[REFRESCO].value)[CLAIM_ALCANCE] == "enrolar_mfa"


def test_la_sesion_restringida_no_abre_el_resto_de_la_api(navegador, docente):
    navegador.login(docente.correo)
    respuesta = navegador.get("/api/cualquiera")
    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "sin_permiso"
    assert navegador.enviar("/api/cualquiera").status_code == 403


def test_la_sesion_restringida_si_puede_consultar_sus_pendientes(navegador, docente):
    navegador.login(docente.correo)
    respuesta = navegador.get("/api/auth/yo")
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "nombre": "Docente Demo",
        "rol": "DOCENTE",
        "pendientes": {"cambiar_password": True, "enrolar_mfa": True},
    }


def test_renovar_no_convierte_una_sesion_restringida_en_completa(navegador, docente):
    navegador.login(docente.correo)
    respuesta = navegador.enviar("/api/auth/refresh")
    assert respuesta.status_code == 204
    assert AccessToken(respuesta.cookies[ACCESO].value)[CLAIM_ALCANCE] == "enrolar_mfa"
    assert RefreshToken(respuesta.cookies[REFRESCO].value)[CLAIM_ALCANCE] == "enrolar_mfa"
    assert navegador.get("/api/cualquiera").status_code == 403


def test_la_bitacora_deja_constancia_de_que_la_sesion_es_restringida(navegador, docente):
    navegador.login(docente.correo)
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGIN_OK)
    assert registro.actor == docente
    assert registro.detalle == {"sesion": "restringida", "pendiente": "enrolar_mfa"}
    docente.refresh_from_db()
    assert docente.ultimo_acceso is None


# --- Personal con 2FA activado: ninguna sesión hasta verificarlo -------------


@pytest.mark.parametrize("persona", ["docente", "admin"])
def test_el_personal_con_2fa_no_recibe_ninguna_sesion_con_la_contrasena(
    navegador, persona, request
):
    usuario = request.getfixturevalue(persona)
    Usuario.objects.filter(pk=usuario.pk).update(mfa_habilitado=True)
    respuesta = navegador.login(usuario.correo)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"paso": "mfa"}
    assert ACCESO not in respuesta.cookies
    assert REFRESCO not in respuesta.cookies
    assert navegador.get("/api/auth/yo").status_code == 401
    assert navegador.get("/api/cualquiera").status_code == 401
    assert not RegistroAuditoria.objects.filter(accion=Accion.LOGIN_OK).exists()


# --- Segunda barrera: lo que diga el token no basta --------------------------


def test_un_token_completo_no_se_acepta_para_personal_sin_2fa(docente):
    # Aunque por un error se emitiera, la autenticación lo rechaza.
    navegador = _con_tokens(docente, Alcance.COMPLETA)
    assert navegador.get("/api/cualquiera").status_code == 401
    assert navegador.get("/api/auth/yo").status_code == 401
    assert navegador.enviar("/api/auth/refresh").status_code == 401


def test_un_token_sin_alcance_o_con_un_alcance_desconocido_no_sirve(alumno):
    for alcance in (None, "", "todo", "COMPLETA", 1):
        refresco = RefreshToken.for_user(alumno)
        refresco[CLAIM_VERSION] = alumno.version_sesion
        if alcance is not None:
            refresco[CLAIM_ALCANCE] = alcance
        navegador = Navegador()
        navegador.cookies[ACCESO] = str(refresco.access_token)
        navegador.cookies[REFRESCO] = str(refresco)
        assert navegador.get("/api/auth/yo").status_code == 401, alcance
        assert navegador.enviar("/api/auth/refresh").status_code == 401, alcance


def test_emitir_tokens_no_acepta_un_alcance_inventado(alumno):
    with pytest.raises(ValueError):
        emitir_tokens(alumno, "todo")


# --- Sesión completa ---------------------------------------------------------


def test_un_alumno_con_sesion_completa_usa_la_api(navegador, alumno):
    navegador.login(alumno.correo)
    assert navegador.get("/api/cualquiera").status_code == 200
    assert navegador.enviar("/api/cualquiera").status_code == 200
    assert navegador.enviar("/api/cualquiera", con_csrf=False).status_code == 403


def test_con_contrasena_temporal_la_sesion_no_abre_el_resto_de_la_api(navegador, alumno):
    Usuario.objects.filter(pk=alumno.pk).update(debe_cambiar_password=True)
    navegador.login(alumno.correo)
    assert navegador.get("/api/cualquiera").status_code == 403
    pendientes = navegador.get("/api/auth/yo").json()["pendientes"]
    assert pendientes == {"cambiar_password": True, "enrolar_mfa": False}


def test_sin_sesion_la_api_responde_401(navegador):
    assert navegador.get("/api/cualquiera").status_code == 401
