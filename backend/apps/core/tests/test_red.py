"""Pruebas de la IP del cliente con cabeceras falsificadas."""

import pytest
from django.conf import settings
from django.test import RequestFactory

from apps.core.red import ip_del_cliente, normalizar_ip

# Direcciones reservadas para documentación (RFC 5737 y RFC 3849).
PROXY = "10.0.0.5"
CLIENTE = "203.0.113.7"
FALSA = "198.51.100.99"
OTRA_FALSA = "192.0.2.44"


def _peticion(remota: str = PROXY, reenvio: str | None = None):
    cabeceras = {"REMOTE_ADDR": remota}
    if reenvio is not None:
        cabeceras["HTTP_X_FORWARDED_FOR"] = reenvio
    return RequestFactory().post("/api/auth/login", **cabeceras)


@pytest.fixture
def sin_proxy(settings):
    settings.PROXIES_DE_CONFIANZA = 0


@pytest.fixture
def con_un_proxy(settings):
    settings.PROXIES_DE_CONFIANZA = 1


def test_fuera_de_produccion_no_se_confia_en_ningun_proxy():
    # Valor por omisión en desarrollo y en las pruebas.
    assert settings.PROXIES_DE_CONFIANZA == 0


# --- Desarrollo: sin proxy --------------------------------------------------


def test_sin_proxy_la_ip_es_la_de_la_conexion(sin_proxy):
    assert ip_del_cliente(_peticion(remota=CLIENTE)) == CLIENTE


@pytest.mark.parametrize(
    "falsificada",
    [FALSA, f"{FALSA}, {OTRA_FALSA}", "127.0.0.1", "::1", "no-es-una-ip", ""],
)
def test_sin_proxy_la_cabecera_se_ignora_por_completo(sin_proxy, falsificada):
    assert ip_del_cliente(_peticion(remota=CLIENTE, reenvio=falsificada)) == CLIENTE


# --- Producción: un proxy de confianza (Azure App Service) -------------------


def test_con_un_proxy_la_ip_es_la_que_agrego_el_proxy(con_un_proxy):
    assert ip_del_cliente(_peticion(reenvio=CLIENTE)) == CLIENTE


@pytest.mark.parametrize(
    "falsificado",
    [
        FALSA,
        f"{FALSA}, {OTRA_FALSA}",
        "127.0.0.1",
        "10.0.0.1",
        "::1",
        "no-es-una-ip",
        "<script>alert(1)</script>",
        "' OR 1=1 --",
    ],
)
def test_lo_que_manda_el_navegador_antes_del_proxy_no_cuenta(con_un_proxy, falsificado):
    # El navegador envía su propia cabecera; el proxy agrega la IP real al final.
    assert ip_del_cliente(_peticion(reenvio=f"{falsificado}, {CLIENTE}")) == CLIENTE


def test_falsificar_la_cabecera_no_cambia_la_ip_entre_peticiones(con_un_proxy):
    # Un atacante que rota la cabecera para esquivar el límite por IP sigue
    # contando siempre como la misma dirección.
    vistas = {
        ip_del_cliente(_peticion(reenvio=f"198.51.100.{numero}, {CLIENTE}"))
        for numero in range(1, 30)
    }
    assert vistas == {CLIENTE}


def test_se_acepta_el_puerto_que_agrega_app_service(con_un_proxy):
    assert ip_del_cliente(_peticion(reenvio=f"{FALSA}, {CLIENTE}:51234")) == CLIENTE
    assert ip_del_cliente(_peticion(reenvio="[2001:db8::1]:51234")) == "2001:db8::1"
    assert ip_del_cliente(_peticion(reenvio="2001:DB8:0:0::1")) == "2001:db8::1"


def test_sin_cabecera_se_usa_la_conexion(con_un_proxy):
    # Por ejemplo, la revisión de estado que hace la plataforma sin pasar por el proxy.
    assert ip_del_cliente(_peticion(remota=PROXY)) == PROXY
    assert ip_del_cliente(_peticion(remota=PROXY, reenvio=" , ")) == PROXY


def test_una_entrada_mal_formada_del_proxy_no_se_usa(con_un_proxy):
    assert ip_del_cliente(_peticion(remota=PROXY, reenvio=f"{FALSA}, basura")) == PROXY


# --- Más de un proxy propio -------------------------------------------------


def test_con_dos_proxies_se_cuenta_desde_el_final(settings):
    settings.PROXIES_DE_CONFIANZA = 2
    # navegador (falsa) → proxy externo agrega CLIENTE → proxy interno agrega 10.0.0.9
    assert ip_del_cliente(_peticion(reenvio=f"{FALSA}, {CLIENTE}, 10.0.0.9")) == CLIENTE
    # Si llegan menos entradas que proxies, no se adivina: se usa la conexión.
    assert ip_del_cliente(_peticion(remota=PROXY, reenvio=CLIENTE)) == PROXY


# --- Normalización -----------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "esperada"),
    [
        ("203.0.113.7", "203.0.113.7"),
        (" 203.0.113.7 ", "203.0.113.7"),
        ("203.0.113.7:443", "203.0.113.7"),
        ("[2001:db8::1]", "2001:db8::1"),
        ("2001:db8::1", "2001:db8::1"),
        ("", None),
        (None, None),
        ("999.1.1.1", None),
        ("203.0.113.7; DROP TABLE", None),
        ("localhost", None),
    ],
)
def test_normalizar_ip(texto, esperada):
    assert normalizar_ip(texto) == esperada


def test_una_peticion_sin_datos_de_conexion_no_tiene_ip(sin_proxy):
    assert ip_del_cliente(object()) is None
