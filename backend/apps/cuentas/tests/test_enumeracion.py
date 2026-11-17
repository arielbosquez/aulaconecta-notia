"""El login no revela si un correo existe (RS-03).

Tres cosas podrían delatarlo: el mensaje, el código de estado y el tiempo de
respuesta. Las dos primeras se comparan directamente. El tiempo se cubre de
dos maneras: una prueba exacta (en todos los caminos se ejecuta Argon2id una
sola vez, que es lo que domina el tiempo) y una medición con margen amplio
para no fallar por el ruido de la máquina.
"""

import statistics
import time
from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth.hashers import Argon2PasswordHasher, identify_hasher
from django.utils import timezone

from apps.cuentas.limites import LimiteDeLoginPorIp
from apps.cuentas.models import Usuario
from apps.cuentas.servicios import _hash_ficticio

from .conftest import CLAVE, OTRA_CLAVE, Navegador, crear_usuario

pytestmark = pytest.mark.django_db

GENERICO = {
    "codigo": "credenciales_invalidas",
    "mensaje": (
        "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente. "
        "Intenta de nuevo en unos minutos."
    ),
}


def _bloquear(usuario):
    Usuario.objects.filter(pk=usuario.pk).update(
        bloqueado_hasta=timezone.now() + settings.LOGIN_DURACION_DEL_BLOQUEO
    )


def _preparar(caso: str, alumno) -> tuple[str, str]:
    """Deja la cuenta en el estado del caso y devuelve el correo y la contraseña a enviar."""
    if caso == "correo_inexistente":
        return "nadie.demo@aulaconecta.cl", CLAVE
    if caso == "cuenta_desactivada":
        Usuario.objects.filter(pk=alumno.pk).update(is_active=False)
        return alumno.correo, CLAVE
    if caso == "contrasena_incorrecta":
        return alumno.correo, OTRA_CLAVE
    if caso == "sin_contrasena_utilizable":
        alumno.set_unusable_password()
        alumno.save(update_fields=["password"])
        return alumno.correo, CLAVE
    if caso == "bloqueada_con_contrasena_incorrecta":
        _bloquear(alumno)
        return alumno.correo, OTRA_CLAVE
    raise AssertionError(caso)


CASOS_GENERICOS = [
    "correo_inexistente",
    "cuenta_desactivada",
    "contrasena_incorrecta",
    "sin_contrasena_utilizable",
    "bloqueada_con_contrasena_incorrecta",
]


def _huella(respuesta) -> tuple:
    """Lo que un atacante ve de una respuesta, sin lo que cambia en cada petición."""
    variables = {"Date", "Retry-After"}
    cabeceras = tuple(
        sorted((nombre, valor) for nombre, valor in respuesta.items() if nombre not in variables)
    )
    return respuesta.status_code, respuesta.content, cabeceras, tuple(sorted(respuesta.cookies))


@pytest.mark.parametrize("caso", CASOS_GENERICOS)
def test_cada_caso_responde_el_mismo_error_generico(navegador, alumno, caso):
    correo, password = _preparar(caso, alumno)
    respuesta = navegador.login(correo, password)
    assert respuesta.status_code == 401
    assert respuesta.json() == GENERICO


def test_las_respuestas_son_identicas_byte_a_byte(admin):
    huellas = {}
    for numero, caso in enumerate(CASOS_GENERICOS):
        # Una cuenta y un navegador por caso, para que no se afecten entre sí.
        persona = crear_usuario(
            f"caso{numero}.demo@aulaconecta.cl",
            consentimiento_verificado_en=timezone.now(),
            consentimiento_verificado_por=admin,
        )
        navegador = Navegador()
        correo, password = _preparar(caso, persona)
        huellas[caso] = _huella(navegador.login(correo, password))
    assert len(set(huellas.values())) == 1, huellas


def _contar_hashes(navegador, correo, password) -> tuple[int, int]:
    original = Argon2PasswordHasher.verify
    with mock.patch.object(
        Argon2PasswordHasher, "verify", autospec=True, side_effect=original
    ) as verificar:
        respuesta = navegador.login(correo, password)
    return respuesta.status_code, verificar.call_count


@pytest.mark.parametrize("caso", CASOS_GENERICOS)
def test_cada_caso_generico_calcula_argon2id_una_sola_vez(navegador, alumno, caso):
    correo, password = _preparar(caso, alumno)
    assert _contar_hashes(navegador, correo, password) == (401, 1)


def test_un_ingreso_correcto_tambien_calcula_argon2id_una_sola_vez(navegador, alumno):
    assert _contar_hashes(navegador, alumno.correo, CLAVE) == (200, 1)


def test_con_la_cuenta_bloqueada_cualquier_contrasena_calcula_argon2id_una_sola_vez(
    navegador, alumno
):
    _bloquear(alumno)
    assert _contar_hashes(navegador, alumno.correo, OTRA_CLAVE) == (401, 1)
    assert _contar_hashes(navegador, alumno.correo, CLAVE) == (401, 1)


def test_el_hash_ficticio_es_argon2id_y_no_corresponde_a_ninguna_contrasena_conocida():
    ficticio = _hash_ficticio()
    assert identify_hasher(ficticio).algorithm == "argon2"
    # Es el mismo durante todo el proceso: se calcula una sola vez.
    assert _hash_ficticio() is ficticio
    for intento in ("", CLAVE, OTRA_CLAVE, "password", "!"):
        assert not Argon2PasswordHasher().verify(intento, ficticio)


def _mediana_en_ms(navegador, correo, password, veces=5) -> float:
    tiempos = []
    for _ in range(veces):
        inicio = time.perf_counter()
        navegador.login(correo, password)
        tiempos.append((time.perf_counter() - inicio) * 1000)
    return statistics.median(tiempos)


def test_el_tiempo_de_respuesta_es_similar_exista_o_no_el_correo(
    navegador, alumno, settings, monkeypatch
):
    # Más intentos que el límite por IP en esta prueba: se sube solo aquí.
    monkeypatch.setattr(LimiteDeLoginPorIp, "THROTTLE_RATES", {"login": "1000/min"})
    # El bloqueo cambiaría de camino a mitad de la medición: se alarga el límite.
    settings.LOGIN_INTENTOS_ANTES_DE_BLOQUEAR = 1000
    navegador.login("calentamiento.demo@aulaconecta.cl", CLAVE)

    inexistente = _mediana_en_ms(navegador, "nadie.demo@aulaconecta.cl", CLAVE)
    incorrecta = _mediana_en_ms(navegador, alumno.correo, OTRA_CLAVE)
    # Sin el hash ficticio, el correo inexistente respondería en una fracción
    # del tiempo (Argon2id es la mayor parte). El margen es amplio a propósito.
    assert 0.6 <= inexistente / incorrecta <= 1.6, (inexistente, incorrecta)
