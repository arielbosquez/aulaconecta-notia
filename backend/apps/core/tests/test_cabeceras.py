"""Pruebas del middleware de cabeceras de seguridad y de la CSP (RS-13)."""

import base64
import hashlib
import json

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.middleware import (
    CabecerasSeguridadMiddleware,
    construir_csp,
    leer_hashes,
)


def _hash(texto: str) -> str:
    resumen = hashlib.sha256(texto.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(resumen).decode("ascii")


def _responder(peticion):
    respuesta = HttpResponse("ok")
    # Una vista no puede relajar la política: el middleware la vuelve a fijar.
    respuesta["Content-Security-Policy"] = "default-src *"
    return respuesta


@pytest.fixture
def archivo_hashes(tmp_path, settings):
    ruta = tmp_path / "csp-hashes.json"
    settings.CSP_ARCHIVO_HASHES = ruta
    return ruta


@pytest.fixture
def fabrica():
    return RequestFactory()


def _directivas(csp: str) -> dict[str, str]:
    pares = (parte.strip().split(" ", 1) for parte in csp.split(";"))
    return {nombre: fuentes for nombre, fuentes in pares}


def test_agrega_todas_las_cabeceras(archivo_hashes, fabrica):
    respuesta = CabecerasSeguridadMiddleware(_responder)(fabrica.get("/"))

    assert respuesta["X-Content-Type-Options"] == "nosniff"
    assert respuesta["Referrer-Policy"] == "same-origin"
    assert respuesta["Cross-Origin-Opener-Policy"] == "same-origin"
    assert respuesta["Cross-Origin-Resource-Policy"] == "same-origin"
    for funcion in ("camera", "microphone", "geolocation", "payment"):
        assert f"{funcion}=()" in respuesta["Permissions-Policy"]
    assert respuesta["Content-Security-Policy"].startswith("default-src 'self'")


def test_la_csp_es_la_de_la_arquitectura_y_sin_unsafe(archivo_hashes, fabrica):
    csp = CabecerasSeguridadMiddleware(_responder)(fabrica.get("/"))["Content-Security-Policy"]

    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert "*" not in csp
    assert _directivas(csp) == {
        "default-src": "'self'",
        "script-src": "'self'",
        "style-src": "'self'",
        "img-src": "'self' blob: data:",
        "media-src": "'self' blob:",
        "connect-src": "'self'",
        "font-src": "'self'",
        "object-src": "'none'",
        "base-uri": "'none'",
        "frame-ancestors": "'none'",
        "form-action": "'self'",
    }


def test_incluye_los_hashes_del_build_de_astro(archivo_hashes, fabrica):
    de_script, de_estilo = _hash("console.log(1)"), _hash("body{margin:0}")
    archivo_hashes.write_text(
        json.dumps({"script": [de_script], "style": [de_estilo]}), encoding="utf-8"
    )

    csp = CabecerasSeguridadMiddleware(_responder)(fabrica.get("/"))["Content-Security-Policy"]

    directivas = _directivas(csp)
    assert directivas["script-src"] == f"'self' '{de_script}'"
    assert directivas["style-src"] == f"'self' '{de_estilo}'"


def test_descarta_hashes_mal_formados_o_con_inyeccion(archivo_hashes):
    bueno = _hash("ok")
    archivo_hashes.write_text(
        json.dumps(
            {
                "script": [
                    bueno,
                    "sha256-corto",
                    "'unsafe-inline'",
                    bueno + "'; script-src *",
                    42,
                ],
                "style": "no-es-una-lista",
                "otro": [bueno],
            }
        ),
        encoding="utf-8",
    )

    hashes = leer_hashes(archivo_hashes)

    assert hashes == {"script": (bueno,), "style": ()}
    assert "unsafe" not in construir_csp(hashes)


@pytest.mark.parametrize("contenido", ["", "{no es json", "[]", '"texto"'])
def test_archivo_danado_deja_la_politica_sin_hashes(archivo_hashes, contenido):
    archivo_hashes.write_text(contenido, encoding="utf-8")
    assert leer_hashes(archivo_hashes) == {"script": (), "style": ()}


def test_sin_archivo_la_politica_no_permite_codigo_en_linea(archivo_hashes):
    assert not archivo_hashes.exists()
    assert leer_hashes(archivo_hashes) == {"script": (), "style": ()}


def test_la_api_no_se_guarda_en_cache(archivo_hashes, fabrica):
    middleware = CabecerasSeguridadMiddleware(_responder)

    assert middleware(fabrica.get("/api/auth/yo"))["Cache-Control"] == "no-store"
    assert "Cache-Control" not in middleware(fabrica.get("/ingresar"))


def test_hsts_solo_con_https_y_configurado(archivo_hashes, fabrica, settings):
    settings.SECURE_HSTS_SECONDS = 0
    sin_hsts = CabecerasSeguridadMiddleware(_responder)
    assert "Strict-Transport-Security" not in sin_hsts(fabrica.get("/", secure=True))

    settings.SECURE_HSTS_SECONDS = 31_536_000
    settings.SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    settings.SECURE_HSTS_PRELOAD = True
    con_hsts = CabecerasSeguridadMiddleware(_responder)
    assert "Strict-Transport-Security" not in con_hsts(fabrica.get("/"))
    assert (
        con_hsts(fabrica.get("/", secure=True))["Strict-Transport-Security"]
        == "max-age=31536000; includeSubDomains; preload"
    )


def test_el_middleware_esta_instalado_y_va_primero(settings):
    assert settings.MIDDLEWARE[0] == "apps.core.middleware.CabecerasSeguridadMiddleware"


def test_una_ruta_inexistente_tambien_lleva_las_cabeceras(client):
    respuesta = client.get("/api/no-existe")

    assert respuesta.status_code == 404
    assert "default-src 'self'" in respuesta["Content-Security-Policy"]
    assert respuesta["X-Content-Type-Options"] == "nosniff"
    assert respuesta["X-Frame-Options"] == "DENY"
    assert respuesta["Cache-Control"] == "no-store"
