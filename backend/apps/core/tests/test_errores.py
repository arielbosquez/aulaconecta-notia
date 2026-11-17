"""Pruebas del manejo de errores genérico (RS-18)."""

import logging

import pytest
from django.test import Client

from apps.core.tests.urls_errores import DETALLE_INTERNO

pytestmark = pytest.mark.urls("apps.core.tests.urls_errores")

FRAGMENTOS_PROHIBIDOS = (
    DETALLE_INTERNO,
    "clave-ficticia-interna",
    "Traceback",
    "RuntimeError",
    "cuentas_usuario",
    ".py",
)


def _sin_detalles_internos(respuesta) -> None:
    texto = respuesta.content.decode("utf-8")
    for fragmento in FRAGMENTOS_PROHIBIDOS:
        assert fragmento not in texto


@pytest.fixture
def cliente():
    # Como en producción: un fallo de la vista se convierte en respuesta 500.
    return Client(raise_request_exception=False)


def test_error_forzado_responde_generico_y_sin_traza(cliente, caplog):
    with caplog.at_level(logging.ERROR, logger="apps.core.errores"):
        respuesta = cliente.get("/api/inesperado")

    assert respuesta.status_code == 500
    assert respuesta.json() == {
        "codigo": "error_interno",
        "mensaje": "Ocurrió un error inesperado. Inténtalo de nuevo más tarde.",
    }
    _sin_detalles_internos(respuesta)
    # El detalle sí queda en el servidor, con su traza.
    assert any(registro.exc_info for registro in caplog.records)
    assert "GET /api/inesperado" in caplog.text


def test_error_de_vista_de_django_tambien_es_generico(cliente):
    respuesta = cliente.get("/api/django-falla")

    assert respuesta.status_code == 500
    assert respuesta["Content-Type"] == "application/json"
    assert respuesta.json()["codigo"] == "error_interno"
    _sin_detalles_internos(respuesta)


def test_error_de_negocio_muestra_su_codigo_y_mensaje(cliente):
    respuesta = cliente.get("/api/negocio")

    assert respuesta.status_code == 409
    assert respuesta.json() == {
        "codigo": "pregunta_no_disponible",
        "mensaje": "La pregunta ya no está disponible",
    }


@pytest.mark.parametrize(
    ("ruta", "estado", "codigo"),
    [
        ("/api/no-encontrado-drf", 404, "no_encontrado"),
        ("/api/no-encontrado-django", 404, "no_encontrado"),
        ("/api/ruta-que-no-existe", 404, "no_encontrado"),
        ("/api/denegado-django", 403, "sin_permiso"),
        # Sin sesión: la autenticación por cookie responde 401, no 403.
        ("/api/protegida", 401, "no_autenticado"),
        ("/api/servicio", 500, "error_interno"),
    ],
)
def test_los_errores_no_repiten_el_mensaje_de_la_excepcion(cliente, ruta, estado, codigo):
    respuesta = cliente.get(ruta)

    assert respuesta.status_code == estado
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"codigo", "mensaje"}
    assert cuerpo["codigo"] == codigo
    _sin_detalles_internos(respuesta)


def test_metodo_no_permitido(cliente):
    respuesta = cliente.delete("/api/ok")

    assert respuesta.status_code == 405
    assert respuesta.json()["codigo"] == "metodo_no_permitido"


def test_limite_de_tasa_indica_cuando_reintentar(cliente):
    respuesta = cliente.get("/api/limite")

    assert respuesta.status_code == 429
    assert respuesta.json()["codigo"] == "demasiadas_solicitudes"
    assert int(respuesta["Retry-After"]) >= 30


def test_validacion_indica_los_campos_sin_exponer_nada_mas(cliente):
    respuesta = cliente.post(
        "/api/ok", data={"correo": "no-es-correo", "edad": 0}, content_type="application/json"
    )

    assert respuesta.status_code == 400
    cuerpo = respuesta.json()
    assert cuerpo["codigo"] == "datos_invalidos"
    assert cuerpo["mensaje"] == "Revisa los datos ingresados."
    assert set(cuerpo["detalle"]) == {"correo", "edad"}


def test_json_mal_formado_es_solicitud_invalida(cliente):
    respuesta = cliente.post("/api/ok", data="{esto no es json", content_type="application/json")

    assert respuesta.status_code == 400
    assert respuesta.json() == {
        "codigo": "solicitud_invalida",
        "mensaje": "La solicitud no es válida.",
    }


def test_formato_no_soportado(cliente):
    respuesta = cliente.post("/api/ok", data="a=1", content_type="text/plain")

    assert respuesta.status_code == 415
    assert respuesta.json()["codigo"] == "formato_no_soportado"


def test_rechazo_csrf_responde_json_generico():
    cliente = Client(enforce_csrf_checks=True)

    respuesta = cliente.post("/api/django-formulario", data={"a": "1"})

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "csrf_invalido"
    assert "CSRF cookie" not in respuesta.content.decode("utf-8")


def test_los_errores_tambien_llevan_las_cabeceras_de_seguridad(cliente):
    respuesta = cliente.get("/api/inesperado")

    assert "default-src 'self'" in respuesta["Content-Security-Policy"]
    assert respuesta["Cache-Control"] == "no-store"
    assert respuesta["X-Content-Type-Options"] == "nosniff"


@pytest.mark.urls("config.urls")
def test_el_proyecto_real_responde_json_en_rutas_inexistentes(cliente):
    respuesta = cliente.get("/admin/")

    assert respuesta.status_code == 404
    assert respuesta.json()["codigo"] == "no_encontrado"


def test_debug_esta_apagado_fuera_de_desarrollo(settings):
    assert settings.DEBUG is False
    assert settings.REST_FRAMEWORK["EXCEPTION_HANDLER"] == (
        "apps.core.errores.manejador_de_excepciones"
    )
