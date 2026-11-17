"""El uso de un refresco ya usado queda en la bitácora, sin guardar el token (RA-02)."""

from datetime import timedelta

import pytest
import time_machine
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.cuentas.tokens import emitir_tokens

from .conftest import Navegador

pytestmark = pytest.mark.django_db

ACCESO = settings.COOKIE_ACCESO
REFRESCO = settings.COOKIE_REFRESCO
REFRESH = "/api/auth/refresh"


def _renovar_con(refresco: str, **extra):
    otro = Navegador()
    otro.cookies[REFRESCO] = refresco
    return otro.enviar(REFRESH, **extra)


def _avisos():
    return RegistroAuditoria.objects.filter(
        accion=Accion.ACCESO_DENEGADO, detalle__motivo="refresco_reutilizado"
    )


def _refresco_ya_rotado(navegador, alumno) -> str:
    usado = navegador.login(alumno.correo).cookies[REFRESCO].value
    assert navegador.enviar(REFRESH).status_code == 204
    return usado


def test_reutilizar_un_refresco_queda_en_la_bitacora(navegador, alumno):
    usado = _refresco_ya_rotado(navegador, alumno)
    respuesta = _renovar_con(usado, REMOTE_ADDR="198.51.100.23", HTTP_USER_AGENT="Otro navegador")
    # Para quien lo usa, la respuesta es la misma de siempre.
    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "sesion_expirada"

    aviso = _avisos().get()
    # Sin actor: quien lo usó pudo no ser el dueño. La cuenta queda como objeto.
    assert aviso.actor is None
    assert (aviso.objeto_tipo, aviso.objeto_id) == ("cuentas.Usuario", str(alumno.pk))
    assert aviso.ip == "198.51.100.23"
    assert aviso.user_agent == "Otro navegador"
    assert aviso.detalle == {"motivo": "refresco_reutilizado"}


def test_el_registro_nunca_guarda_el_token(navegador, alumno):
    usado = _refresco_ya_rotado(navegador, alumno)
    _renovar_con(usado)
    jti = RefreshToken(usado, verify=False)["jti"]
    for registro in RegistroAuditoria.objects.all():
        texto = f"{registro.detalle} {registro.objeto_id} {registro.user_agent}"
        assert usado not in texto
        assert jti not in texto
        assert "eyJ" not in texto


def test_un_refresco_usado_despues_del_logout_tambien_queda_registrado(navegador, alumno):
    refresco = navegador.login(alumno.correo).cookies[REFRESCO].value
    navegador.enviar("/api/auth/logout")
    _renovar_con(refresco)
    assert _avisos().count() == 1


def test_repetirlo_muchas_veces_deja_un_solo_registro_por_minuto(navegador, alumno):
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        usado = _refresco_ya_rotado(navegador, alumno)
        for _ in range(5):
            assert _renovar_con(usado).status_code == 401
        assert _avisos().count() == 1
    with time_machine.travel(inicio + timedelta(seconds=61), tick=False):
        _renovar_con(usado)
        assert _avisos().count() == 2


def test_cada_refresco_reutilizado_tiene_su_propio_registro(alumno):
    primero, segundo = Navegador(), Navegador()
    usado_1 = _refresco_ya_rotado(primero, alumno)
    usado_2 = _refresco_ya_rotado(segundo, alumno)
    _renovar_con(usado_1)
    _renovar_con(usado_2)
    assert _avisos().count() == 2


def test_una_renovacion_normal_no_deja_aviso(navegador, alumno):
    navegador.login(alumno.correo)
    for _ in range(3):
        assert navegador.enviar(REFRESH).status_code == 204
    assert not _avisos().exists()


def test_un_refresco_vencido_no_deja_aviso(navegador, alumno):
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        usado = _refresco_ya_rotado(navegador, alumno)
    with time_machine.travel(inicio + timedelta(hours=8, minutes=1), tick=False):
        assert _renovar_con(usado).status_code == 401
    assert not _avisos().exists()


def test_un_token_falso_o_firmado_con_otra_llave_no_deja_aviso(navegador, alumno, settings):
    usado = _refresco_ya_rotado(navegador, alumno)
    cabecera, cuerpo, _firma = usado.split(".")
    _renovar_con(f"{cabecera}.{cuerpo}.firma-inventada")
    _renovar_con("esto-no-es-un-token")
    assert not _avisos().exists()


def test_un_token_de_acceso_en_la_cookie_de_refresco_no_deja_aviso(navegador, alumno):
    acceso = navegador.login(alumno.correo).cookies[ACCESO].value
    assert _renovar_con(acceso).status_code == 401
    assert not _avisos().exists()


def test_un_refresco_anulado_por_cambio_de_contrasena_no_es_reutilizacion(alumno):
    # Su versión quedó vieja, pero nadie lo usó: no está en la lista negra.
    tokens = emitir_tokens(alumno, "completa")
    alumno.cerrar_todas_las_sesiones()
    alumno.save(update_fields=["version_sesion"])
    assert _renovar_con(tokens.refresco).status_code == 401
    assert not _avisos().exists()
