"""Pruebas del servicio que escribe en la bitácora y del modelo RegistroAuditoria."""

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import RequestFactory
from django.utils import timezone

from apps.auditoria.models import Accion, BitacoraInmutable, RegistroAuditoria
from apps.auditoria.servicios import limpiar_detalle, origen_de, registrar
from apps.core.registros import MASCARA

# Valores ficticios: ninguno debe llegar a la bitácora.
CLAVE_FICTICIA = "clave-ficticia-de-prueba"
JWT_FICTICIO = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.firma-ficticia"

ACCIONES_MINIMAS = {
    "LOGIN_OK", "LOGIN_FALLIDO", "CUENTA_BLOQUEADA", "CUENTA_DESBLOQUEADA", "MFA_OK",
    "MFA_FALLIDO", "MFA_ACTIVADO", "MFA_REINICIADO", "LOGOUT", "PASSWORD_CAMBIADA",
    "PASSWORD_RESTABLECIDA", "ACCESO_DENEGADO", "USUARIO_CREADO", "USUARIO_MODIFICADO",
    "USUARIO_DESACTIVADO", "CONSENTIMIENTO_REGISTRADO", "EVALUACION_CREADA",
    "EVALUACION_PUBLICADA", "EVALUACION_VERSIONADA", "EVALUACION_CERRADA", "MODALIDAD_ASIGNADA",
    "INTENTO_INICIADO", "INTENTO_FINALIZADO", "INTENTO_REABIERTO", "PREGUNTA_ANULADA",
    "CORRECCION_MODIFICADA", "NOTAS_PUBLICADAS", "DATOS_EXPORTADOS", "ALUMNO_ANONIMIZADO",
    "DATOS_PURGADOS",
}  # fmt: skip


@pytest.fixture
def docente(db):
    return get_user_model().objects.create_user(
        "docente.demo@aulaconecta.cl", nombres="Docente", apellidos="Demo"
    )


def _peticion(**cabeceras):
    return RequestFactory().post("/api/auth/login", **cabeceras)


# --- Lo que no necesita base de datos ---------------------------------------


def test_estan_todas_las_acciones_de_la_arquitectura():
    assert set(Accion.values) == ACCIONES_MINIMAS
    largo = RegistroAuditoria._meta.get_field("accion").max_length
    assert all(len(valor) <= largo for valor in Accion.values)


def test_el_detalle_enmascara_lo_que_la_bitacora_no_guarda():
    limpio = limpiar_detalle(
        {
            "password": CLAVE_FICTICIA,
            "contraseña_fallida": CLAVE_FICTICIA,
            "token_refresco": JWT_FICTICIO,
            "codigo_2fa": "123456",
            "alternativa_elegida": str(uuid.uuid4()),
            "texto_pregunta": "¿Cuál es la capital de Chile?",
            "enunciado": "¿Cuál es la capital de Chile?",
            "motivo": "bloqueo por intentos",
            "intentos": 5,
        }
    )
    assert limpio == {
        "password": MASCARA,
        "contraseña_fallida": MASCARA,
        "token_refresco": MASCARA,
        "codigo_2fa": MASCARA,
        "alternativa_elegida": MASCARA,
        "texto_pregunta": MASCARA,
        "enunciado": MASCARA,
        "motivo": "bloqueo por intentos",
        "intentos": 5,
    }


def test_el_detalle_tambien_se_limpia_por_dentro():
    pregunta = uuid.uuid4()
    limpio = limpiar_detalle(
        {
            "preguntas": [pregunta],
            "cambios": {"nombres": "Alumna", "password": CLAVE_FICTICIA},
            "nota": f"se recibió Authorization: Bearer {JWT_FICTICIO}",
        }
    )
    assert limpio["preguntas"] == [str(pregunta)]
    assert limpio["cambios"] == {"nombres": "Alumna", "password": MASCARA}
    assert JWT_FICTICIO not in limpio["nota"]
    assert CLAVE_FICTICIA not in str(limpio)


def test_el_detalle_vacio_es_un_diccionario_y_no_acepta_otra_cosa():
    assert limpiar_detalle(None) == {}
    with pytest.raises(TypeError):
        limpiar_detalle(["no", "es", "un", "diccionario"])


def test_origen_usa_la_ip_de_la_conexion_y_recorta_el_navegador():
    ip, navegador = origen_de(
        _peticion(
            REMOTE_ADDR="203.0.113.7",
            HTTP_USER_AGENT="N" * 500,
            HTTP_X_FORWARDED_FOR="198.51.100.99",
        )
    )
    # Sin proxy de confianza, la cabecera X-Forwarded-For no se usa.
    assert ip == "203.0.113.7"
    assert navegador == "N" * 200


def test_origen_detras_del_proxy_usa_la_entrada_que_agrego_el_proxy(settings):
    settings.PROXIES_DE_CONFIANZA = 1
    ip, _ = origen_de(
        _peticion(REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="198.51.100.99, 203.0.113.7:51234")
    )
    assert ip == "203.0.113.7"


@pytest.mark.parametrize("direccion", ["", "no-es-una-ip", "203.0.113.7; DROP TABLE"])
def test_origen_descarta_una_ip_mal_formada(direccion):
    assert origen_de(_peticion(REMOTE_ADDR=direccion)) == (None, "")


def test_origen_sin_peticion():
    assert origen_de(None) == (None, "")


# --- Escritura en PostgreSQL -------------------------------------------------


def test_registrar_guarda_quien_que_cuando_y_desde_donde(docente):
    antes = timezone.now()
    registro = registrar(
        Accion.LOGIN_OK,
        actor=docente,
        peticion=_peticion(REMOTE_ADDR="203.0.113.7", HTTP_USER_AGENT="Navegador de prueba"),
    )
    guardado = RegistroAuditoria.objects.get(pk=registro.pk)
    assert guardado.accion == Accion.LOGIN_OK
    assert guardado.actor == docente
    assert guardado.ip == "203.0.113.7"
    assert guardado.user_agent == "Navegador de prueba"
    assert guardado.detalle == {}
    assert antes - timedelta(seconds=5) <= guardado.ocurrido_en <= timezone.now()
    assert str(guardado).startswith("LOGIN_OK · ")


def test_registrar_sin_actor_ni_peticion(db):
    registro = registrar(Accion.LOGIN_FALLIDO, detalle={"motivo": "correo desconocido"})
    guardado = RegistroAuditoria.objects.get(pk=registro.pk)
    assert guardado.actor is None
    assert guardado.rol_actor == ""
    assert guardado.ip is None
    assert guardado.detalle == {"motivo": "correo desconocido"}


def test_registrar_anota_el_objeto_afectado(docente):
    registro = registrar(Accion.USUARIO_MODIFICADO, actor=docente, objeto=docente)
    assert registro.objeto_tipo == "cuentas.Usuario"
    assert registro.objeto_id == str(docente.pk)


def test_registrar_nunca_guarda_datos_prohibidos(docente):
    registro = registrar(
        Accion.LOGIN_FALLIDO,
        actor=docente,
        detalle={"password": CLAVE_FICTICIA, "token": JWT_FICTICIO, "intentos": 3},
    )
    guardado = RegistroAuditoria.objects.get(pk=registro.pk)
    assert guardado.detalle == {"password": MASCARA, "token": MASCARA, "intentos": 3}


def test_registrar_rechaza_una_accion_desconocida(db):
    with pytest.raises(ValueError):
        registrar("ACCION_INVENTADA")
    assert not RegistroAuditoria.objects.exists()


def test_la_base_tambien_rechaza_una_accion_desconocida(db):
    with pytest.raises(IntegrityError), transaction.atomic():
        RegistroAuditoria.objects.create(accion="ACCION_INVENTADA")


def test_registrar_exige_un_actor_guardado(db):
    sin_guardar = get_user_model()(correo="alumno.demo@aulaconecta.cl")
    sin_guardar.pk = None
    with pytest.raises(ValueError, match="actor"):
        registrar(Accion.LOGIN_OK, actor=sin_guardar)


def test_los_registros_salen_del_mas_reciente_al_mas_antiguo(db):
    primero = registrar(Accion.LOGIN_FALLIDO)
    segundo = registrar(Accion.LOGIN_OK)
    assert list(RegistroAuditoria.objects.all()) == [segundo, primero]


# --- El modelo no deja modificar ni borrar -----------------------------------


def test_el_modelo_no_deja_modificar_un_registro(docente):
    registro = registrar(Accion.LOGIN_OK, actor=docente)
    registro.accion = Accion.LOGOUT
    with pytest.raises(BitacoraInmutable):
        registro.save()
    with pytest.raises(BitacoraInmutable):
        RegistroAuditoria.objects.filter(pk=registro.pk).update(accion=Accion.LOGOUT)
    assert RegistroAuditoria.objects.get(pk=registro.pk).accion == Accion.LOGIN_OK


def test_el_modelo_no_deja_borrar_un_registro(docente):
    registro = registrar(Accion.LOGIN_OK, actor=docente)
    with pytest.raises(BitacoraInmutable):
        registro.delete()
    with pytest.raises(BitacoraInmutable):
        RegistroAuditoria.objects.all().delete()
    assert RegistroAuditoria.objects.filter(pk=registro.pk).exists()


def test_un_usuario_con_historial_no_se_puede_borrar(docente):
    registrar(Accion.LOGIN_OK, actor=docente)
    with pytest.raises(ProtectedError):
        docente.delete()
    assert get_user_model().objects.filter(pk=docente.pk).exists()
