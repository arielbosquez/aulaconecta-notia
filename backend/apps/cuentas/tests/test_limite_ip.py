"""Límite de 10 peticiones de login por minuto por IP (RS-02)."""

from datetime import timedelta
from unittest import mock

import pytest
import time_machine
from django.conf import settings
from django.contrib.auth.hashers import Argon2PasswordHasher
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from apps.cuentas.limites import LimiteDeLoginPorIp, identificador_de_red
from apps.cuentas.vistas import VistaLogin

from .conftest import CLAVE, OTRA_CLAVE

pytestmark = pytest.mark.django_db

IP = "203.0.113.7"
OTRA_IP = "198.51.100.23"
# Correos que no existen: así los intentos no bloquean ninguna cuenta.
INEXISTENTE = "nadie.demo@aulaconecta.cl"


def _gastar_el_limite(navegador, **extra):
    for numero in range(10):
        respuesta = navegador.login(f"nadie{numero}.demo@aulaconecta.cl", OTRA_CLAVE, **extra)
        assert respuesta.status_code == 401, f"la petición {numero + 1} no debía limitarse"


def test_el_login_tiene_el_limite_de_la_arquitectura():
    assert LimiteDeLoginPorIp in VistaLogin.throttle_classes
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] == "10/min"


def test_la_peticion_11_del_minuto_responde_429(navegador):
    _gastar_el_limite(navegador, REMOTE_ADDR=IP)
    respuesta = navegador.login(INEXISTENTE, OTRA_CLAVE, REMOTE_ADDR=IP)
    assert respuesta.status_code == 429
    assert respuesta.json() == {
        "codigo": "demasiadas_solicitudes",
        "mensaje": "Demasiados intentos. Espera un momento y vuelve a intentarlo.",
    }
    assert 1 <= int(respuesta["Retry-After"]) <= 61


def test_pasado_el_limite_ni_la_contrasena_correcta_entra_ni_se_calcula_el_hash(
    navegador, alumno
):
    _gastar_el_limite(navegador, REMOTE_ADDR=IP)
    with mock.patch.object(Argon2PasswordHasher, "verify") as verificar:
        respuesta = navegador.login(alumno.correo, CLAVE, REMOTE_ADDR=IP)
    assert respuesta.status_code == 429
    verificar.assert_not_called()
    assert settings.COOKIE_ACCESO not in respuesta.cookies


def test_el_limite_es_por_ip(navegador, alumno):
    _gastar_el_limite(navegador, REMOTE_ADDR=IP)
    assert navegador.login(alumno.correo, REMOTE_ADDR=OTRA_IP).status_code == 200


def test_el_limite_se_libera_pasado_el_minuto(navegador, alumno):
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        _gastar_el_limite(navegador, REMOTE_ADDR=IP)
        assert navegador.login(alumno.correo, REMOTE_ADDR=IP).status_code == 429
    with time_machine.travel(inicio + timedelta(seconds=61), tick=False):
        assert navegador.login(alumno.correo, REMOTE_ADDR=IP).status_code == 200


def test_las_peticiones_rechazadas_por_csrf_tambien_cuentan(navegador):
    for _ in range(10):
        assert navegador.login(INEXISTENTE, con_csrf=False, REMOTE_ADDR=IP).status_code == 403
    assert navegador.login(INEXISTENTE, REMOTE_ADDR=IP).status_code == 429


def test_una_cabecera_falsificada_no_esquiva_el_limite(navegador):
    # Sin proxy (desarrollo), X-Forwarded-For se ignora por completo.
    for numero in range(10):
        navegador.login(INEXISTENTE, REMOTE_ADDR=IP, HTTP_X_FORWARDED_FOR=f"192.0.2.{numero}")
    respuesta = navegador.login(INEXISTENTE, REMOTE_ADDR=IP, HTTP_X_FORWARDED_FOR="192.0.2.99")
    assert respuesta.status_code == 429


def test_detras_del_proxy_cuenta_la_ip_que_agrega_azure(navegador, settings):
    settings.PROXIES_DE_CONFIANZA = 1
    proxy = "10.0.0.5"
    # El navegador cambia lo que escribe al inicio de la cabecera; Azure
    # agrega al final la IP real, que es la que se cuenta.
    for numero in range(10):
        navegador.login(
            INEXISTENTE, REMOTE_ADDR=proxy, HTTP_X_FORWARDED_FOR=f"192.0.2.{numero}, {IP}"
        )
    limitada = navegador.login(
        INEXISTENTE, REMOTE_ADDR=proxy, HTTP_X_FORWARDED_FOR=f"192.0.2.99, {IP}"
    )
    assert limitada.status_code == 429
    # Otra persona detrás del mismo proxy tiene su propio contador.
    otra = navegador.login(INEXISTENTE, REMOTE_ADDR=proxy, HTTP_X_FORWARDED_FOR=OTRA_IP)
    assert otra.status_code == 401


def test_una_ipv6_se_cuenta_por_su_bloque_64(navegador):
    for numero in range(10):
        navegador.login(INEXISTENTE, REMOTE_ADDR=f"2001:db8:1:2::{numero + 1:x}")
    # Otra dirección del mismo /64: mismo contador.
    assert navegador.login(INEXISTENTE, REMOTE_ADDR="2001:db8:1:2:ffff::1").status_code == 429
    # Otro bloque /64: contador propio.
    assert navegador.login(INEXISTENTE, REMOTE_ADDR="2001:db8:1:3::1").status_code == 401


@pytest.mark.parametrize(
    ("ip", "esperado"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:abcd:ef01:2345:6789", "2001:db8:1:2::/64"),
        # IPv4 vista por un servidor que escucha en IPv6: cuenta como IPv4.
        ("::ffff:203.0.113.7", "203.0.113.7"),
        (None, "desconocida"),
        ("", "desconocida"),
    ],
)
def test_identificador_de_red(ip, esperado):
    assert identificador_de_red(ip) == esperado


def test_el_conteo_se_guarda_en_la_cache_de_base_de_datos(navegador):
    assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
    navegador.login(INEXISTENTE, REMOTE_ADDR=IP)
    # La prueba corre como notia_app: la tabla la creó la migración con
    # notia_owner y la aplicación solo escribe filas en ella.
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user, count(*) FROM notia_cache")
        rol, filas = cursor.fetchone()
    assert rol == "notia_app"
    assert filas == 1
    assert cache.get(f"throttle_login_{IP}") is not None


def test_notia_app_no_puede_cambiar_la_tabla_de_la_cache():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = 'notia_cache'"
        )
        assert cursor.fetchone() == ("notia_owner",)
        cursor.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'notia_app' AND table_name = 'notia_cache' ORDER BY 1"
        )
        permisos = [fila[0] for fila in cursor.fetchall()]
    assert permisos == ["DELETE", "INSERT", "SELECT", "UPDATE"]
