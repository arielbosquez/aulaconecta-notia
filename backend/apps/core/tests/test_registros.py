"""Pruebas del logging en JSON sin datos sensibles (sección 12.8)."""

import io
import json
import logging
import sys

import pytest
from django.conf import settings
from django.test import RequestFactory

from apps.core.registros import (
    MASCARA,
    FiltroDatosSensibles,
    FormateadorJson,
    enmascarar_dato,
    enmascarar_texto,
)

# Valores ficticios: ninguno debe sobrevivir al filtro.
SECRETO = "valor-ficticio-123"
JWT_FICTICIO = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.firma-ficticia"


@pytest.fixture
def registrar():
    """Devuelve una función que registra algo y entrega la línea JSON resultante."""
    salida = io.StringIO()
    manejador = logging.StreamHandler(salida)
    manejador.setFormatter(FormateadorJson())
    manejador.addFilter(FiltroDatosSensibles())
    registro = logging.getLogger("notia.prueba.registros")
    registro.addHandler(manejador)
    registro.setLevel(logging.DEBUG)
    registro.propagate = False

    def _registrar(mensaje, *args, **kwargs):
        salida.seek(0)
        salida.truncate()
        registro.log(kwargs.pop("nivel", logging.INFO), mensaje, *args, **kwargs)
        linea = salida.getvalue()
        assert linea.count("\n") == 1, "cada registro debe ocupar una sola línea"
        return json.loads(linea), linea

    yield _registrar
    registro.removeHandler(manejador)


@pytest.mark.parametrize(
    "texto",
    [
        f"password={SECRETO}",
        f"contraseña: {SECRETO}",
        f'{{"password": "{SECRETO}", "correo": "alumno.demo@aulaconecta.cl"}}',
        f"GET /api/x?token={SECRETO}&pagina=2",
        f"Cookie: notia_acceso={SECRETO}",
        f"csrftoken={SECRETO}; otra=1",
        f"codigo_mfa={SECRETO}",
        f"alternativa_id={SECRETO}",
        f"MFA_ENCRYPTION_KEY='{SECRETO}'",
        f"Authorization: Bearer {SECRETO}",
    ],
)
def test_enmascara_valores_sensibles_en_un_texto(texto):
    resultado = enmascarar_texto(texto)

    assert SECRETO not in resultado
    assert MASCARA in resultado


def test_enmascara_tokens_por_su_forma():
    assert JWT_FICTICIO not in enmascarar_texto(f"se recibió {JWT_FICTICIO} en la petición")


def test_no_toca_lo_que_no_es_sensible():
    texto = "Usuario creado: rol=ALUMNO curso=2° Medio A pagina=3"
    assert enmascarar_texto(texto) == texto


def test_enmascara_datos_adicionales_por_nombre_y_en_profundidad():
    datos = {"usuario": "demo", "password": SECRETO, "interno": {"refresh_token": SECRETO}}

    resultado = enmascarar_dato("detalle", datos)

    assert resultado == {
        "usuario": "demo",
        "password": MASCARA,
        "interno": {"refresh_token": MASCARA},
    }
    assert enmascarar_dato("cookies", {"cualquiera": SECRETO}) == MASCARA


def test_cada_registro_es_un_json_con_los_campos_base(registrar):
    datos, _ = registrar("Evaluación %s publicada", "demo", nivel=logging.WARNING)

    assert datos["nivel"] == "WARNING"
    assert datos["origen"] == "notia.prueba.registros"
    assert datos["mensaje"] == "Evaluación demo publicada"
    assert datos["momento"].endswith("+00:00")


def test_el_mensaje_y_sus_argumentos_salen_enmascarados(registrar):
    _, linea = registrar("Intento de login con password=%s y token %s", SECRETO, JWT_FICTICIO)

    assert SECRETO not in linea
    assert JWT_FICTICIO not in linea


def test_los_datos_adicionales_salen_enmascarados(registrar):
    datos, linea = registrar(
        "Login",
        extra={"correo_hash": "abc", "password": SECRETO, "cabeceras": {"Cookie": SECRETO}},
    )

    assert SECRETO not in linea
    assert datos["correo_hash"] == "abc"
    assert datos["password"] == MASCARA


def test_de_la_peticion_solo_se_registra_metodo_y_ruta(registrar):
    peticion = RequestFactory().post(
        f"/api/auth/login?token={SECRETO}",
        data={"password": SECRETO},
        HTTP_COOKIE=f"notia_acceso={SECRETO}",
        HTTP_AUTHORIZATION=f"Bearer {SECRETO}",
    )

    datos, linea = registrar("Petición rechazada", extra={"request": peticion, "status_code": 403})

    assert SECRETO not in linea
    assert datos["metodo"] == "POST"
    assert datos["ruta"] == "/api/auth/login"
    assert datos["status_code"] == 403
    assert "request" not in datos


def test_la_traza_de_una_excepcion_sale_enmascarada(registrar):
    try:
        raise ValueError(f"fallo con password={SECRETO}")
    except ValueError:
        datos, linea = registrar("Error", exc_info=sys.exc_info(), nivel=logging.ERROR)

    assert SECRETO not in linea
    assert "ValueError" in datos["excepcion"]


def test_un_objeto_desconocido_no_se_vuelca_al_registro(registrar):
    class Sesion:
        def __repr__(self):
            return f"Sesion(token={SECRETO})"

    datos, linea = registrar("Sesión", extra={"sesion": Sesion(), "lista": [Sesion()]})

    assert SECRETO not in linea
    assert "sesion" not in datos


def test_la_configuracion_usa_json_y_el_filtro_en_la_salida_estandar():
    consola = settings.LOGGING["handlers"]["consola"]

    assert consola["stream"] == "ext://sys.stdout"
    assert consola["filters"] == ["datos_sensibles"]
    assert settings.LOGGING["formatters"]["json"]["()"] == "apps.core.registros.FormateadorJson"
    assert settings.LOGGING["root"]["handlers"] == ["consola"]
    # Las consultas SQL (con datos de personas) no se registran.
    assert settings.LOGGING["loggers"]["django.db.backends"]["level"] == "WARNING"
