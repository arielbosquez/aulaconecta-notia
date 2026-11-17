"""Cierre de sesión, cambio de contraseña e invalidación de sesiones (CU-03, CU-04, RS-04)."""

from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.cuentas.models import Rol, Usuario
from apps.cuentas.servicios import MENSAJE_CONTRASENA_ACTUAL_INCORRECTA
from apps.cuentas.tokens import CLAIM_ALCANCE, CLAIM_VERSION, Alcance

from .conftest import CLAVE, OTRA_CLAVE, Navegador, crear_usuario

pytestmark = [pytest.mark.django_db, pytest.mark.urls("apps.cuentas.tests.urls_sesion")]

ACCESO = settings.COOKIE_ACCESO
REFRESCO = settings.COOKIE_REFRESCO
NUEVA = "Glaciar-Naranjo-58"
OTRA_NUEVA = "Volcan-Celeste-31"
CAMBIAR = "/api/auth/cambiar-password"
LOGOUT = "/api/auth/logout"
REFRESH = "/api/auth/refresh"


def _yo(navegador):
    return navegador.get("/api/auth/yo")


def _cambiar(navegador, actual=CLAVE, nueva=NUEVA, **extra):
    return navegador.enviar(CAMBIAR, {"password_actual": actual, "password_nueva": nueva}, **extra)


def _con_cookies(acceso=None, refresco=None) -> Navegador:
    """Otro navegador con cookies copiadas (por ejemplo, robadas)."""
    otro = Navegador()
    if acceso:
        otro.cookies[ACCESO] = acceso
    if refresco:
        otro.cookies[REFRESCO] = refresco
    return otro


def _cookie_borrada(respuesta, nombre, ruta):
    cookie = respuesta.cookies[nombre]
    assert cookie.value == ""
    assert cookie["max-age"] == 0
    assert cookie["path"] == ruta
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == "Strict"


# --- Cierre de sesión (CU-03) -------------------------------------------------


def test_el_logout_borra_las_dos_cookies_con_sus_mismos_atributos(navegador, alumno):
    navegador.login(alumno.correo)
    respuesta = navegador.enviar(LOGOUT)
    assert respuesta.status_code == 204
    assert respuesta.content == b""
    _cookie_borrada(respuesta, ACCESO, "/")
    _cookie_borrada(respuesta, REFRESCO, "/api/auth/")
    assert _yo(navegador).status_code == 401


def test_el_logout_pone_el_refresco_en_la_lista_negra(navegador, alumno):
    refresco = navegador.login(alumno.correo).cookies[REFRESCO].value
    navegador.enviar(LOGOUT)
    jti = RefreshToken(refresco, verify=False)["jti"]
    assert BlacklistedToken.objects.filter(token__jti=jti).exists()


def test_un_refresco_copiado_antes_del_logout_ya_no_sirve(navegador, alumno):
    refresco = navegador.login(alumno.correo).cookies[REFRESCO].value
    navegador.enviar(LOGOUT)
    respuesta = _con_cookies(refresco=refresco).enviar(REFRESH)
    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "sesion_expirada"


def test_el_logout_queda_en_la_bitacora(navegador, alumno):
    login = navegador.login(alumno.correo)
    navegador.enviar(LOGOUT, REMOTE_ADDR="203.0.113.7")
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGOUT)
    assert registro.actor == alumno
    assert registro.ip == "203.0.113.7"
    for cookie in login.cookies.values():
        assert cookie.value not in str(registro.detalle)


def test_el_logout_funciona_con_el_token_de_acceso_vencido(navegador, alumno):
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        refresco = navegador.login(alumno.correo).cookies[REFRESCO].value
    with time_machine.travel(inicio + timedelta(minutes=6), tick=False):
        assert _yo(navegador).status_code == 401
        assert navegador.enviar(LOGOUT).status_code == 204
        assert _con_cookies(refresco=refresco).enviar(REFRESH).status_code == 401
    assert RegistroAuditoria.objects.filter(accion=Accion.LOGOUT, actor=alumno).exists()


def test_el_logout_sin_sesion_solo_borra_las_cookies(navegador):
    respuesta = navegador.enviar(LOGOUT)
    assert respuesta.status_code == 204
    _cookie_borrada(respuesta, ACCESO, "/")
    assert not RegistroAuditoria.objects.filter(accion=Accion.LOGOUT).exists()


def test_el_logout_con_cookies_falsas_no_falla_ni_registra(navegador):
    navegador.cookies[ACCESO] = "esto-no-es-un-token"
    navegador.cookies[REFRESCO] = "tampoco-esto"
    assert navegador.enviar(LOGOUT).status_code == 204
    assert not RegistroAuditoria.objects.filter(accion=Accion.LOGOUT).exists()


def test_el_logout_exige_csrf_y_sin_el_no_anula_nada(navegador, alumno):
    navegador.login(alumno.correo)
    respuesta = navegador.enviar(LOGOUT, con_csrf=False)
    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "csrf_invalido"
    assert _yo(navegador).status_code == 200
    assert navegador.enviar(REFRESH).status_code == 204


def test_el_logout_rota_el_token_csrf(navegador, alumno):
    navegador.login(alumno.correo)
    antes = navegador.cookies["csrftoken"].value
    navegador.enviar(LOGOUT)
    assert navegador.cookies["csrftoken"].value != antes


def test_el_logout_solo_cierra_la_sesion_de_ese_navegador(alumno):
    casa, colegio = Navegador(), Navegador()
    casa.login(alumno.correo)
    colegio.login(alumno.correo)
    casa.enviar(LOGOUT)
    assert _yo(casa).status_code == 401
    assert _yo(colegio).status_code == 200
    assert colegio.enviar(REFRESH).status_code == 204


def test_una_sesion_restringida_tambien_puede_cerrar_sesion(navegador, docente):
    assert navegador.login(docente.correo).json()["paso"] == "enrolar_mfa"
    assert navegador.enviar(LOGOUT).status_code == 204
    assert RegistroAuditoria.objects.filter(accion=Accion.LOGOUT, actor=docente).exists()


def test_el_logout_solo_acepta_post(navegador):
    assert navegador.get(LOGOUT).status_code == 405


# --- Contraseña temporal ------------------------------------------------------


@pytest.fixture
def con_temporal(alumno):
    Usuario.objects.filter(pk=alumno.pk).update(debe_cambiar_password=True)
    alumno.refresh_from_db()
    return alumno


def test_con_la_contrasena_temporal_solo_se_puede_cambiarla_o_cerrar_sesion(
    navegador, con_temporal
):
    respuesta = navegador.login(con_temporal.correo)
    assert respuesta.json() == {"paso": "listo", "debe_cambiar_password": True}
    assert navegador.get("/api/cualquiera").status_code == 403
    assert navegador.enviar("/api/cualquiera").status_code == 403
    assert _yo(navegador).json()["pendientes"]["cambiar_password"] is True

    assert _cambiar(navegador).status_code == 204
    assert navegador.get("/api/cualquiera").status_code == 200
    assert _yo(navegador).json()["pendientes"]["cambiar_password"] is False
    con_temporal.refresh_from_db()
    assert con_temporal.debe_cambiar_password is False


def test_la_contrasena_temporal_deja_de_servir(navegador, con_temporal):
    navegador.login(con_temporal.correo)
    _cambiar(navegador)
    assert Navegador().login(con_temporal.correo, CLAVE).status_code == 401
    respuesta = Navegador().login(con_temporal.correo, NUEVA)
    assert respuesta.json() == {"paso": "listo", "debe_cambiar_password": False}


def test_el_personal_con_contrasena_temporal_la_cambia_desde_la_sesion_restringida(
    navegador, docente
):
    # Docente recién creado: contraseña temporal y sin 2FA.
    assert docente.debe_cambiar_password is True
    assert navegador.login(docente.correo).json()["paso"] == "enrolar_mfa"
    assert _cambiar(navegador, nueva="Archipielago-Morado-73").status_code == 204
    # Sigue restringida: cambiar la contraseña no reemplaza al 2FA.
    acceso = AccessToken(navegador.cookies[ACCESO].value)
    assert acceso[CLAIM_ALCANCE] == Alcance.ENROLAR_MFA
    assert navegador.get("/api/cualquiera").status_code == 403
    assert _yo(navegador).json()["pendientes"] == {
        "cambiar_password": False,
        "enrolar_mfa": True,
    }


# --- Cambio de contraseña (CU-04) ---------------------------------------------


def test_cambiar_la_contrasena_sin_sesion_responde_401(navegador):
    assert _cambiar(navegador).status_code == 401


def test_cambiar_la_contrasena_exige_csrf(navegador, alumno):
    navegador.login(alumno.correo)
    assert _cambiar(navegador, con_csrf=False).status_code == 403
    alumno.refresh_from_db()
    assert alumno.check_password(CLAVE)


def test_cambiar_la_contrasena_exige_la_actual(navegador, alumno):
    navegador.login(alumno.correo)
    respuesta = _cambiar(navegador, actual=OTRA_CLAVE)
    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "password_actual_incorrecta",
        "mensaje": MENSAJE_CONTRASENA_ACTUAL_INCORRECTA,
    }
    alumno.refresh_from_db()
    assert alumno.check_password(CLAVE)
    assert alumno.intentos_fallidos == 1
    # La sesión sigue abierta: el error no la cierra.
    assert _yo(navegador).status_code == 200


def test_la_contrasena_actual_incorrecta_queda_en_la_bitacora(navegador, alumno):
    navegador.login(alumno.correo)
    _cambiar(navegador, actual=OTRA_CLAVE)
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGIN_FALLIDO)
    assert registro.detalle == {"motivo": "password_actual_incorrecta", "intentos_fallidos": 1}
    assert registro.objeto_id == str(alumno.pk)


def test_una_sesion_robada_no_sirve_para_adivinar_la_contrasena(navegador, alumno):
    navegador.login(alumno.correo)
    for _ in range(5):
        assert _cambiar(navegador, actual=OTRA_CLAVE).status_code == 400
    alumno.refresh_from_db()
    assert alumno.esta_bloqueado()
    # Durante el bloqueo, la contraseña correcta responde igual que una
    # incorrecta y no se cambia nada.
    correcta = _cambiar(navegador, actual=CLAVE)
    incorrecta = _cambiar(navegador, actual=OTRA_CLAVE)
    assert (correcta.status_code, correcta.content) == (incorrecta.status_code, incorrecta.content)
    alumno.refresh_from_db()
    assert alumno.check_password(CLAVE)
    assert RegistroAuditoria.objects.filter(accion=Accion.CUENTA_BLOQUEADA).count() == 1


@pytest.mark.parametrize(
    ("nueva", "motivo"),
    [
        ("Corta-1", "al menos 10 caracteres"),
        ("1234567890123", "completamente numérica"),
        ("password123", "demasiado común"),
        ("alumno.demo@aulaconecta.cl", "similar"),
        (CLAVE, "distinta de la actual"),
    ],
)
def test_la_contrasena_nueva_debe_cumplir_la_politica(navegador, alumno, nueva, motivo):
    navegador.login(alumno.correo)
    respuesta = _cambiar(navegador, nueva=nueva)
    assert respuesta.status_code == 400
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "datos_invalidos"
    assert any(motivo in mensaje for mensaje in cuerpo["detalle"]["password_nueva"]), cuerpo
    alumno.refresh_from_db()
    assert alumno.check_password(CLAVE)


def test_el_personal_necesita_una_contrasena_nueva_de_12_caracteres(navegador, admin):
    # Sesión restringida del administrador (aún sin 2FA).
    navegador.login(admin.correo)
    respuesta = _cambiar(navegador, nueva="Ribera-7-ok")  # 11 caracteres
    assert respuesta.status_code == 400
    assert "al menos 12 caracteres" in str(respuesta.json()["detalle"])
    assert _cambiar(navegador, nueva="Ribera-77-ok").status_code == 204


@pytest.mark.parametrize(
    "datos",
    [
        {},
        {"password_actual": CLAVE},
        {"password_nueva": NUEVA},
        {"password_actual": CLAVE, "password_nueva": "x" * 129},
        {"password_actual": CLAVE, "password_nueva": NUEVA, "debe_cambiar_password": False},
        {"password_actual": [CLAVE], "password_nueva": NUEVA},
    ],
)
def test_el_cambio_valida_la_forma_de_los_datos(navegador, alumno, datos):
    navegador.login(alumno.correo)
    respuesta = navegador.enviar(CAMBIAR, datos)
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "datos_invalidos"


def test_el_cambio_queda_en_la_bitacora_sin_contrasenas(navegador, alumno):
    navegador.login(alumno.correo)
    _cambiar(navegador)
    registro = RegistroAuditoria.objects.get(accion=Accion.PASSWORD_CAMBIADA)
    assert registro.actor == alumno
    assert registro.detalle == {"sesiones_cerradas": True}
    for registro in RegistroAuditoria.objects.all():
        assert CLAVE not in str(registro.detalle)
        assert NUEVA not in str(registro.detalle)


def test_la_contrasena_nueva_se_guarda_con_argon2id(navegador, alumno):
    navegador.login(alumno.correo)
    _cambiar(navegador)
    alumno.refresh_from_db()
    assert alumno.password.startswith("argon2$argon2id$")
    assert NUEVA not in alumno.password


# --- Invalidación de sesiones -------------------------------------------------


def test_cambiar_la_contrasena_cierra_las_sesiones_de_otros_navegadores(alumno):
    propio, otro = Navegador(), Navegador()
    propio.login(alumno.correo)
    otro.login(alumno.correo)
    assert _cambiar(propio).status_code == 204

    assert _yo(otro).status_code == 401
    assert otro.enviar(REFRESH).status_code == 401
    # Quien cambió la contraseña sigue dentro con un par nuevo.
    assert _yo(propio).status_code == 200


def test_los_tokens_anteriores_de_este_mismo_navegador_tampoco_sirven(navegador, alumno):
    login = navegador.login(alumno.correo)
    acceso_viejo = login.cookies[ACCESO].value
    refresco_viejo = login.cookies[REFRESCO].value
    respuesta = _cambiar(navegador)
    assert respuesta.cookies[ACCESO].value != acceso_viejo
    assert respuesta.cookies[REFRESCO].value != refresco_viejo

    assert _yo(_con_cookies(acceso=acceso_viejo)).status_code == 401
    assert _con_cookies(refresco=refresco_viejo).enviar(REFRESH).status_code == 401


def test_cambiar_la_contrasena_sube_la_version_de_sesion_en_uno(navegador, alumno):
    version = alumno.version_sesion
    navegador.login(alumno.correo)
    respuesta = _cambiar(navegador)
    alumno.refresh_from_db()
    assert alumno.version_sesion == version + 1
    nuevo = AccessToken(respuesta.cookies[ACCESO].value)
    assert nuevo[CLAIM_VERSION] == version + 1
    assert nuevo[CLAIM_ALCANCE] == Alcance.COMPLETA


def test_las_cookies_nuevas_tienen_los_mismos_atributos(navegador, alumno):
    navegador.login(alumno.correo)
    respuesta = _cambiar(navegador)
    for nombre, ruta in ((ACCESO, "/"), (REFRESCO, "/api/auth/")):
        cookie = respuesta.cookies[nombre]
        assert (cookie["httponly"], cookie["secure"], cookie["samesite"], cookie["path"]) == (
            True,
            True,
            "Strict",
            ruta,
        )
    assert "eyJ" not in respuesta.content.decode()


def test_el_cambio_rota_el_token_csrf(navegador, alumno):
    navegador.login(alumno.correo)
    antes = navegador.cookies["csrftoken"].value
    _cambiar(navegador)
    assert navegador.cookies["csrftoken"].value != antes


def test_tras_el_cambio_la_sesion_nueva_rota_y_cierra_como_cualquier_otra(navegador, alumno):
    navegador.login(alumno.correo)
    _cambiar(navegador)
    primero = navegador.cookies[REFRESCO].value
    assert navegador.enviar(REFRESH).status_code == 204
    assert navegador.cookies[REFRESCO].value != primero
    assert _con_cookies(refresco=primero).enviar(REFRESH).status_code == 401
    assert navegador.enviar(LOGOUT).status_code == 204
    assert _yo(navegador).status_code == 401


def test_cambiar_la_contrasena_dos_veces_seguidas(navegador, alumno):
    navegador.login(alumno.correo)
    assert _cambiar(navegador).status_code == 204
    assert _cambiar(navegador, actual=NUEVA, nueva=OTRA_NUEVA).status_code == 204
    alumno.refresh_from_db()
    assert alumno.check_password(OTRA_NUEVA)
    assert alumno.version_sesion == 3


def test_desactivar_la_cuenta_corta_tambien_el_cambio_de_contrasena(navegador, alumno):
    navegador.login(alumno.correo)
    Usuario.objects.filter(pk=alumno.pk).update(is_active=False)
    assert _cambiar(navegador).status_code == 401


def test_el_cambio_funciona_igual_para_cada_rol(admin):
    for rol in (Rol.ALUMNO, Rol.DOCENTE):
        persona = crear_usuario(
            f"{rol.lower()}.cambio@aulaconecta.cl",
            rol,
            consentimiento_verificado_en=timezone.now() if rol == Rol.ALUMNO else None,
            consentimiento_verificado_por=admin if rol == Rol.ALUMNO else None,
        )
        navegador = Navegador()
        navegador.login(persona.correo)
        assert _cambiar(navegador, nueva="Meseta-Granate-2024x").status_code == 204
