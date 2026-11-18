"""Preparación de las pruebas de las pantallas en un navegador real (PR 1.6).

Django sirve el build de Astro con WhiteNoise y la API real, con la base de
pruebas de PostgreSQL conectada como ``notia_app`` (``backend/conftest.py``).
Cada página llega con la CSP real, así que una violación de CSP aparece igual
que en producción.

Antes de ejecutarlas:

    cd frontend; npm run build          # dist/ y csp-hashes.json
    cd backend; python -m playwright install chromium
    pytest -m e2e
"""

import os

import pytest
from django.conf import settings
from django.core.cache import cache

pytestmark = pytest.mark.e2e

# Registra cada violación de CSP en la página, además de lo que diga la consola.
ESCUCHAR_CSP = """
window.__violacionesCsp = [];
document.addEventListener('securitypolicyviolation', (evento) => {
  window.__violacionesCsp.push(evento.violatedDirective + ' ' + evento.blockedURI);
});
"""


@pytest.fixture(scope="session", autouse=True)
def _orm_junto_a_playwright():
    """Permite usar el ORM en el hilo donde Playwright corre su ciclo de eventos.

    La API sincrónica de Playwright deja un ciclo de eventos abierto en el hilo
    de las pruebas, y Django rechaza entonces el ORM por precaución. Aquí el
    ORM solo prepara datos y vacía la base al final de cada prueba; el
    servidor atiende al navegador en su propio hilo. Dura toda la sesión
    porque el vaciado ocurre después de que terminan los fixtures de cada
    prueba. Solo se activa al ejecutar estas pruebas.
    """
    anterior = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    yield
    if anterior is None:
        os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
    else:
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = anterior


@pytest.fixture
def servidor(live_server, usar_rol_bd):
    """Dirección del servidor de pruebas, con el build del frontend servido por Django.

    La prueba y el servidor usan ``notia_app``; al terminar se cambia a
    ``notia_owner`` solo para que pytest-django vacíe las tablas (necesita
    TRUNCATE, que la aplicación no tiene). La siguiente prueba vuelve a
    ``notia_app`` antes de empezar.
    """
    if not settings.WHITENOISE_ROOT or not settings.CSP_ARCHIVO_HASHES.is_file():
        pytest.fail(
            "Falta el build del frontend. Ejecuta antes: cd frontend; npm run build",
            pytrace=False,
        )
    usar_rol_bd("app")
    # Los límites de intentos viven en la caché, que el vaciado de la base no toca.
    cache.clear()
    yield live_server.url
    usar_rol_bd("owner")


@pytest.fixture
def pagina(servidor, page):
    """Página del navegador que falla si hay errores de CSP o de JavaScript."""
    consola_csp: list[str] = []
    errores_js: list[str] = []
    page.add_init_script(ESCUCHAR_CSP)
    page.on(
        "console",
        lambda mensaje: (
            consola_csp.append(mensaje.text)
            if "Content Security Policy" in mensaje.text or "Refused to" in mensaje.text
            else None
        ),
    )
    page.on("pageerror", lambda error: errores_js.append(str(error)))
    page.set_default_timeout(10_000)

    yield page

    violaciones = []
    if not page.is_closed():
        violaciones = page.evaluate("window.__violacionesCsp || []")
    assert not consola_csp, f"Errores de CSP en la consola: {consola_csp}"
    assert not violaciones, f"Violaciones de CSP: {violaciones}"
    assert not errores_js, f"Errores de JavaScript: {errores_js}"
