"""Bloqueo de la cuenta tras 5 intentos fallidos y su registro en la bitácora (RS-02, RS-16)."""

import threading
from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.db import connections
from django.utils import timezone

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.core.errores import ErrorApi
from apps.cuentas.models import Rol, Usuario
from apps.cuentas.servicios import _reiniciar_intentos, contar_intento_fallido, iniciar_sesion

from .conftest import CLAVE, OTRA_CLAVE, crear_usuario

MENSAJE_GENERICO = (
    "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente. "
    "Intenta de nuevo en unos minutos."
)
QUINCE_MINUTOS = timedelta(minutes=15)


def _fallar(navegador, usuario, veces: int = 1, **extra):
    for _ in range(veces):
        respuesta = navegador.login(usuario.correo, OTRA_CLAVE, **extra)
        assert respuesta.status_code == 401
    return respuesta


def _estado(usuario) -> Usuario:
    usuario.refresh_from_db()
    return usuario


def _registros(accion, usuario=None):
    registros = RegistroAuditoria.objects.filter(accion=accion)
    if usuario is not None:
        registros = registros.filter(objeto_tipo="cuentas.Usuario", objeto_id=str(usuario.pk))
    return registros


# --- Bloqueo ------------------------------------------------------------------


@pytest.mark.django_db
def test_la_configuracion_es_la_de_la_arquitectura():
    assert settings.LOGIN_INTENTOS_ANTES_DE_BLOQUEAR == 5
    assert settings.LOGIN_DURACION_DEL_BLOQUEO == QUINCE_MINUTOS


@pytest.mark.django_db
def test_cuatro_fallos_seguidos_no_bloquean(navegador, alumno):
    _fallar(navegador, alumno, 4)
    alumno = _estado(alumno)
    assert alumno.intentos_fallidos == 4
    assert alumno.bloqueado_hasta is None
    assert navegador.login(alumno.correo).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("rol", [Rol.ALUMNO, Rol.DOCENTE, Rol.ADMIN])
def test_cinco_fallos_seguidos_bloquean_la_cuenta_por_15_minutos(navegador, admin, rol):
    persona = crear_usuario(
        f"{rol.lower()}.bloqueo@aulaconecta.cl",
        rol,
        consentimiento_verificado_en=timezone.now() if rol == Rol.ALUMNO else None,
        consentimiento_verificado_por=admin if rol == Rol.ALUMNO else None,
    )
    with time_machine.travel(timezone.now(), tick=False):
        _fallar(navegador, persona, 4)
        assert not _estado(persona).esta_bloqueado()
        _fallar(navegador, persona, 1)
        persona = _estado(persona)
        assert persona.bloqueado_hasta == timezone.now() + QUINCE_MINUTOS
        # Al bloquear, el contador vuelve a cero para cuando el bloqueo venza.
        assert persona.intentos_fallidos == 0
    assert persona.esta_bloqueado()


@pytest.mark.django_db
def test_con_la_cuenta_bloqueada_la_contrasena_correcta_no_entra_y_recibe_el_error_generico(
    navegador, alumno
):
    _fallar(navegador, alumno, 5)
    respuesta = navegador.login(alumno.correo, CLAVE)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"codigo": "credenciales_invalidas", "mensaje": MENSAJE_GENERICO}
    assert settings.COOKIE_ACCESO not in respuesta.cookies
    assert settings.COOKIE_REFRESCO not in respuesta.cookies
    assert not _registros(Accion.LOGIN_OK).exists()


@pytest.mark.django_db
def test_con_la_cuenta_bloqueada_una_contrasena_incorrecta_recibe_el_mensaje_generico(
    navegador, alumno
):
    _fallar(navegador, alumno, 5)
    bloqueo = _estado(alumno).bloqueado_hasta
    respuesta = navegador.login(alumno.correo, OTRA_CLAVE)
    assert respuesta.status_code == 401
    assert respuesta.json() == {"codigo": "credenciales_invalidas", "mensaje": MENSAJE_GENERICO}
    # Seguir intentando durante el bloqueo no lo alarga ni suma intentos.
    alumno = _estado(alumno)
    assert alumno.bloqueado_hasta == bloqueo
    assert alumno.intentos_fallidos == 0


@pytest.mark.django_db
def test_una_cuenta_desactivada_no_suma_intentos(navegador, alumno):
    Usuario.objects.filter(pk=alumno.pk).update(is_active=False)
    _fallar(navegador, alumno, 6)
    alumno = _estado(alumno)
    assert alumno.intentos_fallidos == 0
    assert alumno.bloqueado_hasta is None


# --- Desbloqueo ---------------------------------------------------------------


@pytest.mark.django_db
def test_el_bloqueo_vence_a_los_15_minutos(navegador, alumno):
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        _fallar(navegador, alumno, 5)
    with time_machine.travel(inicio + QUINCE_MINUTOS - timedelta(seconds=1), tick=False):
        assert navegador.login(alumno.correo).status_code == 401
    with time_machine.travel(inicio + QUINCE_MINUTOS + timedelta(seconds=1), tick=False):
        respuesta = navegador.login(alumno.correo)
        assert respuesta.status_code == 200
        assert respuesta.json()["paso"] == "listo"
    alumno = _estado(alumno)
    assert alumno.bloqueado_hasta is None
    assert alumno.intentos_fallidos == 0


@pytest.mark.django_db
def test_al_vencer_el_bloqueo_la_cuenta_tiene_otra_vez_5_intentos(navegador, alumno):
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        _fallar(navegador, alumno, 5)
    despues = inicio + QUINCE_MINUTOS + timedelta(seconds=1)
    # El límite por IP es de 10 por minuto: el segundo grupo llega desde otra IP.
    with time_machine.travel(despues, tick=False):
        _fallar(navegador, alumno, 4, REMOTE_ADDR="203.0.113.20")
        assert not _estado(alumno).esta_bloqueado()
        _fallar(navegador, alumno, 1, REMOTE_ADDR="203.0.113.20")
        assert _estado(alumno).bloqueado_hasta == despues + QUINCE_MINUTOS


@pytest.mark.django_db
def test_un_ingreso_correcto_reinicia_el_contador(navegador, alumno):
    _fallar(navegador, alumno, 4)
    assert navegador.login(alumno.correo).status_code == 200
    assert _estado(alumno).intentos_fallidos == 0
    # Los fallos tienen que ser seguidos: 4 más tampoco bloquean.
    _fallar(navegador, alumno, 4)
    assert not _estado(alumno).esta_bloqueado()


@pytest.mark.django_db
def test_un_ingreso_correcto_no_deshace_un_bloqueo_que_otra_peticion_acaba_de_poner(alumno):
    # La petición correcta cargó al usuario antes de que otra lo bloqueara.
    cargado_antes = Usuario.objects.get(pk=alumno.pk)
    cargado_antes.intentos_fallidos = 4
    for _ in range(5):
        contar_intento_fallido(alumno)
    _reiniciar_intentos(cargado_antes)
    assert _estado(alumno).esta_bloqueado()


# --- Peticiones simultáneas ---------------------------------------------------


def _en_paralelo(cantidad: int, funcion) -> list:
    """Ejecuta ``funcion`` en ``cantidad`` hilos que parten al mismo tiempo.

    Cada hilo tiene su propia conexión a PostgreSQL, como cada worker de
    gunicorn en producción. Devuelve lo que devolvió cada hilo.
    """
    barrera = threading.Barrier(cantidad)
    resultados, errores = [], []

    def trabajo():
        try:
            barrera.wait(timeout=30)
            resultados.append(funcion())
        except Exception as error:  # se informa al final, en el hilo principal
            errores.append(error)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=trabajo) for _ in range(cantidad)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=120)
    assert not errores, errores
    assert len(resultados) == cantidad
    return resultados


def _login_fallido(correo: str):
    def intento():
        try:
            iniciar_sesion(correo=correo, password=OTRA_CLAVE)
        except ErrorApi as error:
            return error.status_code
        return 200

    return intento


def _alumno_confirmado():
    admin = crear_usuario("admin.concurrencia@aulaconecta.cl", Rol.ADMIN)
    return crear_usuario(
        "alumno.concurrencia@aulaconecta.cl",
        consentimiento_verificado_en=timezone.now(),
        consentimiento_verificado_por=admin,
    )


def test_contrasenas_incorrectas_simultaneas_se_cuentan_todas(bd_con_transacciones):
    alumno = _alumno_confirmado()
    # Cada petición carga al usuario con 0 intentos y calcula el hash al
    # mismo tiempo que las demás. Si el contador se sumara sobre lo que cada
    # una cargó, todas escribirían 1.
    estados = _en_paralelo(4, _login_fallido(alumno.correo))
    assert estados == [401] * 4
    alumno = _estado(alumno)
    assert alumno.intentos_fallidos == 4
    assert alumno.bloqueado_hasta is None
    assert _registros(Accion.LOGIN_FALLIDO, alumno).count() == 4


def test_de_varias_peticiones_simultaneas_solo_una_bloquea_la_cuenta(bd_con_transacciones):
    alumno = _alumno_confirmado()
    estados = _en_paralelo(6, _login_fallido(alumno.correo))
    assert estados == [401] * 6
    alumno = _estado(alumno)
    assert alumno.esta_bloqueado()
    # El bloqueo se registra una sola vez y no lo alargan las que llegan después.
    assert _registros(Accion.CUENTA_BLOQUEADA, alumno).count() == 1
    assert _registros(Accion.LOGIN_FALLIDO, alumno).count() == 6
    bloqueo = _registros(Accion.CUENTA_BLOQUEADA, alumno).get()
    assert alumno.bloqueado_hasta.isoformat() == bloqueo.detalle["bloqueado_hasta"]


# --- Bitácora -----------------------------------------------------------------


@pytest.mark.django_db
def test_un_correo_inexistente_deja_un_fallo_sin_actor_ni_correo(navegador):
    navegador.login("nadie.demo@aulaconecta.cl", OTRA_CLAVE, REMOTE_ADDR="203.0.113.7")
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGIN_FALLIDO)
    assert registro.actor is None
    assert registro.objeto_id == ""
    assert registro.ip == "203.0.113.7"
    assert registro.detalle == {"motivo": "credenciales"}
    assert "nadie.demo" not in str(registro.detalle)


@pytest.mark.django_db
def test_una_cuenta_desactivada_se_registra_igual_que_un_correo_inexistente(navegador, alumno):
    Usuario.objects.filter(pk=alumno.pk).update(is_active=False)
    navegador.login(alumno.correo)
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGIN_FALLIDO)
    assert (registro.actor, registro.objeto_id, registro.detalle) == (
        None,
        "",
        {"motivo": "credenciales"},
    )


@pytest.mark.django_db
def test_cada_contrasena_incorrecta_queda_en_la_bitacora_con_su_numero(navegador, alumno):
    _fallar(navegador, alumno, 3, REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="Navegador demo")
    registros = _registros(Accion.LOGIN_FALLIDO, alumno).order_by("id")
    assert [r.detalle for r in registros] == [
        {"motivo": "credenciales", "intentos_fallidos": n} for n in (1, 2, 3)
    ]
    for registro in registros:
        # Con la contraseña incorrecta no se sabe quién fue: sin actor.
        assert registro.actor is None
        assert registro.ip == "203.0.113.7"
        assert registro.user_agent == "Navegador demo"


@pytest.mark.django_db
def test_el_bloqueo_queda_en_la_bitacora(navegador, alumno):
    _fallar(navegador, alumno, 5)
    bloqueo = _registros(Accion.CUENTA_BLOQUEADA, alumno).get()
    assert bloqueo.actor is None
    assert bloqueo.detalle["intentos_fallidos"] == 5
    assert bloqueo.detalle["bloqueado_hasta"] == _estado(alumno).bloqueado_hasta.isoformat()


@pytest.mark.django_db
@pytest.mark.parametrize("password", [CLAVE, OTRA_CLAVE])
def test_los_intentos_durante_el_bloqueo_quedan_en_la_bitacora(navegador, alumno, password):
    _fallar(navegador, alumno, 5)
    navegador.login(alumno.correo, password)
    ultimo = _registros(Accion.LOGIN_FALLIDO, alumno).order_by("-id").first()
    # El registro no dice si la contraseña era correcta.
    assert ultimo.detalle == {"motivo": "cuenta_bloqueada"}
    assert _registros(Accion.CUENTA_BLOQUEADA, alumno).count() == 1


@pytest.mark.django_db
def test_el_rechazo_por_falta_de_consentimiento_queda_en_la_bitacora(
    navegador, alumno_sin_consentimiento
):
    navegador.login(alumno_sin_consentimiento.correo)
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGIN_FALLIDO)
    # La contraseña era correcta: aquí sí se sabe quién fue.
    assert registro.actor == alumno_sin_consentimiento
    assert registro.detalle == {"motivo": "sin_consentimiento"}


@pytest.mark.django_db
def test_la_bitacora_nunca_guarda_las_contrasenas_escritas(navegador, alumno):
    _fallar(navegador, alumno, 5)
    navegador.login(alumno.correo, CLAVE)
    navegador.login("nadie.demo@aulaconecta.cl", CLAVE)
    for registro in RegistroAuditoria.objects.all():
        texto = f"{registro.detalle} {registro.objeto_id} {registro.user_agent}"
        assert CLAVE not in texto
        assert OTRA_CLAVE not in texto
