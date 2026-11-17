"""Pruebas del inicio de sesión, las cookies, el CSRF y la renovación (RS-01, RS-04 y RS-05)."""

from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.cuentas.models import Usuario
from apps.cuentas.tokens import CLAIM_ALCANCE, CLAIM_VERSION, Alcance, emitir_tokens
from config.sesion import nombres_de_cookies

from .conftest import CLAVE, OTRA_CLAVE, Navegador

pytestmark = pytest.mark.django_db

ACCESO = settings.COOKIE_ACCESO
REFRESCO = settings.COOKIE_REFRESCO
MENSAJE_GENERICO = "Correo o contraseña incorrectos"


def _yo(navegador):
    return navegador.get("/api/auth/yo")


# --- Inicio de sesión --------------------------------------------------------


def test_un_alumno_con_consentimiento_inicia_sesion(navegador, alumno):
    respuesta = navegador.login(alumno.correo)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"paso": "listo", "debe_cambiar_password": False}
    assert _yo(navegador).status_code == 200


def test_la_respuesta_del_login_no_trae_tokens_en_el_cuerpo(navegador, alumno):
    respuesta = navegador.login(alumno.correo)
    cuerpo = respuesta.content.decode()
    assert respuesta.cookies[ACCESO].value not in cuerpo
    assert respuesta.cookies[REFRESCO].value not in cuerpo
    assert "eyJ" not in cuerpo


def test_el_correo_se_acepta_con_mayusculas_y_espacios(navegador, alumno):
    assert navegador.login("  Alumno.Demo@AulaConecta.CL ").status_code == 200


def test_el_login_avisa_si_hay_que_cambiar_la_contrasena(navegador, alumno):
    Usuario.objects.filter(pk=alumno.pk).update(debe_cambiar_password=True)
    assert navegador.login(alumno.correo).json()["debe_cambiar_password"] is True


def test_el_login_registra_el_acceso_en_la_bitacora(navegador, alumno):
    navegador.login(alumno.correo, REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="Navegador demo")
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGIN_OK)
    assert registro.actor == alumno
    assert registro.rol_actor == "ALUMNO"
    assert registro.ip == "203.0.113.7"
    assert registro.user_agent == "Navegador demo"
    assert CLAVE not in str(registro.detalle)
    alumno.refresh_from_db()
    assert alumno.ultimo_acceso is not None


def test_la_bitacora_no_se_deja_enganar_por_una_cabecera_falsificada(navegador, alumno):
    navegador.login(alumno.correo, REMOTE_ADDR="203.0.113.7", HTTP_X_FORWARDED_FOR="198.51.100.99")
    assert RegistroAuditoria.objects.get(accion=Accion.LOGIN_OK).ip == "203.0.113.7"


@pytest.mark.parametrize(
    ("correo", "password"),
    [
        ("alumno.demo@aulaconecta.cl", OTRA_CLAVE),
        ("alumno.demo@aulaconecta.cl", CLAVE.lower()),
        ("alumno.demo@aulaconecta.cl", CLAVE + " "),
        ("nadie.demo@aulaconecta.cl", CLAVE),
    ],
)
def test_credenciales_incorrectas_responden_siempre_lo_mismo(navegador, alumno, correo, password):
    respuesta = navegador.login(correo, password)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"codigo": "credenciales_invalidas", "mensaje": MENSAJE_GENERICO}
    assert ACCESO not in respuesta.cookies
    assert REFRESCO not in respuesta.cookies
    assert not RegistroAuditoria.objects.filter(accion=Accion.LOGIN_OK).exists()


def test_una_cuenta_desactivada_responde_igual_que_una_inexistente(navegador, alumno):
    Usuario.objects.filter(pk=alumno.pk).update(is_active=False)
    respuesta = navegador.login(alumno.correo)
    assert respuesta.status_code == 401
    assert respuesta.json()["mensaje"] == MENSAJE_GENERICO


def test_una_cuenta_sin_contrasena_utilizable_no_puede_entrar(navegador, alumno):
    alumno.set_unusable_password()
    alumno.save(update_fields=["password"])
    assert navegador.login(alumno.correo, "").status_code == 400
    assert navegador.login(alumno.correo, "!").status_code == 401


@pytest.mark.parametrize(
    "datos",
    [
        {},
        {"correo": "alumno.demo@aulaconecta.cl"},
        {"password": CLAVE},
        {"correo": "no-es-un-correo", "password": CLAVE},
        {"correo": "alumno.demo@aulaconecta.cl", "password": "x" * 129},
        {"correo": "alumno.demo@aulaconecta.cl", "password": CLAVE, "rol": "ADMIN"},
        {"correo": ["alumno.demo@aulaconecta.cl"], "password": {"$ne": ""}},
    ],
)
def test_el_login_valida_la_forma_de_los_datos(navegador, alumno, datos):
    respuesta = navegador.enviar("/api/auth/login", datos)
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "datos_invalidos"
    assert ACCESO not in respuesta.cookies


def test_el_login_solo_acepta_post_y_json(navegador, alumno):
    assert navegador.get("/api/auth/login").status_code == 405
    navegador.pedir_csrf()
    respuesta = navegador.post(
        "/api/auth/login",
        {"correo": alumno.correo, "password": CLAVE},
        HTTP_X_CSRFTOKEN=navegador.cookies["csrftoken"].value,
    )  # formulario multipart, no JSON
    # La API solo lee JSON: un formulario se rechaza sin llegar a las credenciales.
    assert respuesta.status_code in {400, 415}
    assert ACCESO not in respuesta.cookies


def test_una_cookie_de_sesion_invalida_no_impide_volver_a_entrar(navegador, alumno):
    navegador.cookies[ACCESO] = "esto-no-es-un-token"
    assert navegador.login(alumno.correo).status_code == 200


# --- Atributos de las cookies ------------------------------------------------


def test_las_cookies_de_sesion_son_httponly_secure_y_samesite_strict(navegador, alumno):
    respuesta = navegador.login(alumno.correo)
    for nombre in (ACCESO, REFRESCO):
        cookie = respuesta.cookies[nombre]
        assert cookie["httponly"] is True, nombre
        assert cookie["secure"] is True, nombre
        assert cookie["samesite"] == "Strict", nombre
        assert cookie["domain"] == "", nombre


def test_la_cookie_de_acceso_dura_5_minutos_y_la_de_refresco_8_horas(navegador, alumno):
    respuesta = navegador.login(alumno.correo)
    assert respuesta.cookies[ACCESO]["max-age"] == 5 * 60
    assert respuesta.cookies[ACCESO]["path"] == "/"
    assert respuesta.cookies[REFRESCO]["max-age"] == 8 * 60 * 60
    # El refresco solo viaja a las rutas de autenticación.
    assert respuesta.cookies[REFRESCO]["path"] == "/api/auth/"


def test_los_tokens_llevan_la_version_de_sesion_y_la_duracion_correcta(navegador, alumno):
    respuesta = navegador.login(alumno.correo)
    acceso = AccessToken(respuesta.cookies[ACCESO].value)
    refresco = RefreshToken(respuesta.cookies[REFRESCO].value)
    assert acceso["sub"] == refresco["sub"] == str(alumno.pk)
    assert acceso[CLAIM_VERSION] == refresco[CLAIM_VERSION] == 1
    assert acceso["exp"] - acceso["iat"] == 5 * 60
    assert refresco["exp"] - refresco["iat"] == 8 * 60 * 60
    # Nada personal dentro del token: solo identificador, versión, alcance y fechas.
    assert acceso[CLAIM_ALCANCE] == refresco[CLAIM_ALCANCE] == "completa"
    claims = {"token_type", "exp", "iat", "jti", "sub", CLAIM_VERSION, CLAIM_ALCANCE}
    assert set(acceso.payload) == claims


def test_los_nombres_de_las_cookies_llevan_prefijo_solo_en_produccion():
    assert nombres_de_cookies(produccion=True) == {
        "acceso": "__Host-notia_acceso",
        "refresco": "__Secure-notia_refresco",
    }
    assert nombres_de_cookies(produccion=False) == {
        "acceso": "notia_acceso",
        "refresco": "notia_refresco",
    }
    assert (ACCESO, REFRESCO) == ("notia_acceso", "notia_refresco")


def test_la_cookie_csrf_es_legible_por_javascript_y_samesite_strict(navegador):
    respuesta = navegador.get("/api/auth/csrf")
    cookie = respuesta.cookies["csrftoken"]
    assert cookie["httponly"] == ""
    assert cookie["samesite"] == "Strict"
    assert len(cookie.value) >= 32


def test_el_token_csrf_cambia_al_iniciar_sesion(navegador, alumno):
    antes = navegador.pedir_csrf()
    navegador.login(alumno.correo)
    assert navegador.cookies["csrftoken"].value != antes


def test_las_respuestas_de_autenticacion_no_se_guardan_en_cache(navegador, alumno):
    assert navegador.login(alumno.correo)["Cache-Control"] == "no-store"
    assert _yo(navegador)["Cache-Control"] == "no-store"


# --- La firma de los tokens --------------------------------------------------


def test_los_tokens_se_firman_con_una_llave_distinta_de_secret_key():
    assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.JWT_SIGNING_KEY
    assert settings.JWT_SIGNING_KEY
    assert settings.JWT_SIGNING_KEY != settings.SECRET_KEY
    assert settings.SIMPLE_JWT["ALGORITHM"] == "HS256"


def test_un_token_firmado_con_otra_llave_no_sirve(navegador, alumno, settings):
    navegador.login(alumno.correo)
    original = navegador.cookies[ACCESO].value
    cabecera, cuerpo, firma = original.split(".")
    navegador.cookies[ACCESO] = f"{cabecera}.{cuerpo}.{firma[::-1]}"
    assert _yo(navegador).status_code == 401


def test_un_token_sin_firma_no_sirve(navegador, alumno):
    import base64
    import json

    def b64(dato: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(dato).encode()).decode().rstrip("=")

    navegador.login(alumno.correo)
    carga = AccessToken(navegador.cookies[ACCESO].value).payload
    navegador.cookies[ACCESO] = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(carga)}."
    assert _yo(navegador).status_code == 401


def test_el_token_de_refresco_no_sirve_como_token_de_acceso(navegador, alumno):
    navegador.login(alumno.correo)
    navegador.cookies[ACCESO] = navegador.cookies[REFRESCO].value
    assert _yo(navegador).status_code == 401


def test_el_token_no_se_acepta_en_la_cabecera_authorization(alumno):
    tokens = emitir_tokens(alumno, Alcance.COMPLETA)
    sin_cookies = Navegador()
    respuesta = sin_cookies.get("/api/auth/yo", HTTP_AUTHORIZATION=f"Bearer {tokens.acceso}")
    assert respuesta.status_code == 401


# --- Sesión: yo, vencimiento y versión ---------------------------------------


def test_yo_sin_sesion_responde_401(navegador):
    respuesta = _yo(navegador)
    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "no_autenticado"


def test_yo_entrega_solo_nombre_rol_y_pendientes(navegador, alumno):
    navegador.login(alumno.correo)
    assert _yo(navegador).json() == {
        "nombre": "Alumno Demo",
        "rol": "ALUMNO",
        "pendientes": {"cambiar_password": False, "enrolar_mfa": False},
    }


def test_el_token_de_acceso_vence_a_los_5_minutos(navegador, alumno):
    with time_machine.travel(timezone.now(), tick=False) as reloj:
        navegador.login(alumno.correo)
        reloj.shift(timedelta(minutes=4, seconds=59))
        assert _yo(navegador).status_code == 200
        reloj.shift(timedelta(seconds=2))
        assert _yo(navegador).status_code == 401


def test_subir_la_version_de_sesion_invalida_los_tokens_emitidos(navegador, alumno):
    navegador.login(alumno.correo)
    assert _yo(navegador).status_code == 200
    Usuario.objects.filter(pk=alumno.pk).update(version_sesion=2)
    assert _yo(navegador).status_code == 401
    assert navegador.enviar("/api/auth/refresh").status_code == 401


def test_desactivar_la_cuenta_corta_la_sesion(navegador, alumno):
    navegador.login(alumno.correo)
    Usuario.objects.filter(pk=alumno.pk).update(is_active=False)
    assert _yo(navegador).status_code == 401
    assert navegador.enviar("/api/auth/refresh").status_code == 401


# --- CSRF --------------------------------------------------------------------


def test_el_login_sin_token_csrf_responde_403(navegador, alumno):
    respuesta = navegador.login(alumno.correo, con_csrf=False)
    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "csrf_invalido"
    assert ACCESO not in respuesta.cookies


def test_el_login_con_la_cookie_csrf_pero_sin_la_cabecera_responde_403(navegador, alumno):
    navegador.pedir_csrf()
    assert navegador.login(alumno.correo, con_csrf=False).status_code == 403


def test_el_login_con_un_token_csrf_que_no_coincide_responde_403(navegador, alumno):
    navegador.pedir_csrf()
    respuesta = navegador.login(alumno.correo, HTTP_X_CSRFTOKEN="a" * 64)
    assert respuesta.status_code == 403


def test_el_refresh_sin_token_csrf_responde_403_y_no_gasta_el_refresco(navegador, alumno):
    navegador.login(alumno.correo)
    assert navegador.enviar("/api/auth/refresh", con_csrf=False).status_code == 403
    assert not BlacklistedToken.objects.exists()
    assert navegador.enviar("/api/auth/refresh").status_code == 204


def test_una_peticion_autenticada_que_modifica_exige_csrf(navegador, alumno):
    navegador.login(alumno.correo)
    # yo solo admite GET; con sesión y sin CSRF, el rechazo llega antes: 403.
    assert navegador.enviar("/api/auth/yo", con_csrf=False).status_code == 403
    assert navegador.enviar("/api/auth/yo").status_code == 405


def test_el_csrf_no_se_acepta_desde_otro_origen(navegador, alumno):
    navegador.pedir_csrf()
    respuesta = navegador.login(alumno.correo, HTTP_ORIGIN="https://sitio-ajeno.example")
    assert respuesta.status_code == 403


# --- Renovación --------------------------------------------------------------


def test_el_refresh_entrega_un_par_nuevo_y_anula_el_anterior(navegador, alumno):
    login = navegador.login(alumno.correo)
    refresco_viejo = login.cookies[REFRESCO].value
    acceso_viejo = login.cookies[ACCESO].value

    respuesta = navegador.enviar("/api/auth/refresh")
    assert respuesta.status_code == 204
    assert respuesta.content == b""
    assert respuesta.cookies[REFRESCO].value != refresco_viejo
    assert respuesta.cookies[ACCESO].value != acceso_viejo
    assert respuesta.cookies[REFRESCO]["httponly"] is True
    assert respuesta.cookies[REFRESCO]["path"] == "/api/auth/"
    assert _yo(navegador).status_code == 200
    assert BlacklistedToken.objects.count() == 1
    assert OutstandingToken.objects.count() == 2


def test_un_refresco_ya_usado_no_sirve_de_nuevo(navegador, alumno):
    login = navegador.login(alumno.correo)
    robado = login.cookies[REFRESCO].value
    assert navegador.enviar("/api/auth/refresh").status_code == 204

    atacante = Navegador()
    atacante.cookies[REFRESCO] = robado
    respuesta = atacante.enviar("/api/auth/refresh")
    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "sesion_expirada"
    assert ACCESO not in respuesta.cookies or respuesta.cookies[ACCESO].value == ""


def test_un_refresh_rechazado_borra_las_cookies_de_sesion(navegador):
    navegador.cookies[REFRESCO] = "esto-no-es-un-token"
    respuesta = navegador.enviar("/api/auth/refresh")
    assert respuesta.status_code == 401
    for nombre in (ACCESO, REFRESCO):
        assert respuesta.cookies[nombre].value == ""
        assert respuesta.cookies[nombre]["max-age"] == 0
        assert respuesta.cookies[nombre]["httponly"] is True


def test_el_refresh_sin_cookie_responde_401(navegador):
    assert navegador.enviar("/api/auth/refresh").status_code == 401


def test_el_token_de_acceso_no_sirve_para_renovar(navegador, alumno):
    navegador.login(alumno.correo)
    navegador.cookies[REFRESCO] = navegador.cookies[ACCESO].value
    assert navegador.enviar("/api/auth/refresh").status_code == 401


def test_un_refresco_firmado_pero_no_emitido_por_el_servidor_no_sirve(navegador, alumno):
    # Token bien firmado que no pasó por emitir_tokens: no está entre los emitidos.
    suelto = RefreshToken()
    suelto["sub"] = str(alumno.pk)
    suelto[CLAIM_VERSION] = 1
    suelto[CLAIM_ALCANCE] = "completa"
    navegador.cookies[REFRESCO] = str(suelto)
    assert navegador.enviar("/api/auth/refresh").status_code == 401


def test_el_refresco_vence_a_las_8_horas(navegador, alumno):
    with time_machine.travel(timezone.now(), tick=False) as reloj:
        navegador.login(alumno.correo)
        reloj.shift(timedelta(hours=7, minutes=59))
        assert navegador.enviar("/api/auth/refresh").status_code == 204
        reloj.shift(timedelta(hours=8, seconds=1))
        assert navegador.enviar("/api/auth/refresh").status_code == 401


def test_la_sesion_se_mantiene_renovando_durante_la_jornada(navegador, alumno):
    with time_machine.travel(timezone.now(), tick=False) as reloj:
        navegador.login(alumno.correo)
        for _ in range(3):
            reloj.shift(timedelta(minutes=6))
            assert _yo(navegador).status_code == 401
            assert navegador.enviar("/api/auth/refresh").status_code == 204
            assert _yo(navegador).status_code == 200
