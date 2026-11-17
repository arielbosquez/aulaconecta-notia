"""Segundo factor TOTP para docentes y administradores (CU-02, RS-06)."""

import base64
import threading
import time
from datetime import timedelta
from urllib.parse import unquote

import pyotp
import pytest
import time_machine
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import connections
from django.utils import timezone

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.core.errores import ErrorApi
from apps.cuentas.mfa import guardar_secreto, leer_ticket, verificar_segundo_factor
from apps.cuentas.models import CodigoRecuperacion, Rol, Usuario
from apps.cuentas.tokens import CLAIM_ALCANCE, Alcance

from .conftest import CLAVE, Navegador, crear_usuario

ACCESO = settings.COOKIE_ACCESO
REFRESCO = settings.COOKIE_REFRESCO
TICKET = settings.COOKIE_TICKET_MFA
ENROLAR = "/api/auth/mfa/enrolar"
CONFIRMAR = "/api/auth/mfa/confirmar"
VERIFICAR = "/api/auth/mfa/verificar"


def _con_2fa(correo="docente.2fa@aulaconecta.cl", rol=Rol.DOCENTE):
    """Cuenta del personal con el 2FA ya activado. Devuelve la cuenta y su TOTP."""
    persona = crear_usuario(correo, rol, debe_cambiar_password=False)
    secreto = pyotp.random_base32()
    guardar_secreto(persona, secreto)
    persona.mfa_habilitado = True
    persona.save(update_fields=["mfa_secreto_cifrado", "mfa_habilitado"])
    return persona, pyotp.TOTP(secreto)


def _verificar(navegador, codigo, **extra):
    return navegador.enviar(VERIFICAR, {"codigo": codigo}, **extra)


def _iniciar(persona) -> Navegador:
    navegador = Navegador()
    assert navegador.login(persona.correo).json() == {"paso": "mfa"}
    return navegador


def _enrolar(navegador) -> pyotp.TOTP:
    respuesta = navegador.enviar(ENROLAR)
    assert respuesta.status_code == 200, respuesta.json()
    return pyotp.TOTP(respuesta.json()["secreto"])


@pytest.fixture
def docente_listo(db):
    """Docente que ya cambió su contraseña temporal y aún no tiene 2FA."""
    return crear_usuario(
        "docente.enrola@aulaconecta.cl", Rol.DOCENTE, debe_cambiar_password=False
    )


# --- Enrolamiento ---------------------------------------------------------------


@pytest.mark.django_db
def test_el_enrolamiento_exige_haber_cambiado_la_contrasena_temporal(navegador, docente):
    assert docente.debe_cambiar_password is True
    navegador.login(docente.correo)
    respuesta = navegador.enviar(ENROLAR)
    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == "cambiar_password_primero"
    docente.refresh_from_db()
    assert docente.mfa_secreto_cifrado == ""
    # Tras cambiarla, sí puede.
    navegador.enviar(
        "/api/auth/cambiar-password",
        {"password_actual": CLAVE, "password_nueva": "Archipielago-Morado-73"},
    )
    assert navegador.enviar(ENROLAR).status_code == 200


@pytest.mark.django_db
def test_el_qr_es_un_svg_generado_en_el_servidor(navegador, docente_listo):
    navegador.login(docente_listo.correo)
    datos = navegador.enviar(ENROLAR).json()
    assert datos["qr"].startswith("data:image/svg+xml")
    svg = unquote(datos["qr"].split(",", 1)[1])
    assert svg.startswith("<svg") or svg.startswith("<?xml")
    assert "<script" not in svg.lower()
    assert len(base64.b32decode(datos["secreto"])) == 20
    assert (datos["digitos"], datos["intervalo"]) == (6, 30)


@pytest.mark.django_db
def test_el_secreto_se_guarda_cifrado_con_fernet(navegador, docente_listo, settings):
    navegador.login(docente_listo.correo)
    secreto = navegador.enviar(ENROLAR).json()["secreto"]
    docente_listo.refresh_from_db()
    guardado = docente_listo.mfa_secreto_cifrado
    assert secreto not in guardado
    assert Fernet(settings.MFA_ENCRYPTION_KEY).decrypt(guardado.encode()).decode() == secreto
    # Con otra llave no se puede leer: el 2FA queda inutilizable, no expuesto.
    settings.MFA_ENCRYPTION_KEY = Fernet.generate_key().decode()
    respuesta = navegador.enviar(CONFIRMAR, {"codigo": pyotp.TOTP(secreto).now()})
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "mfa_no_disponible"


@pytest.mark.django_db
def test_un_alumno_no_puede_enrolar_un_2fa(navegador, alumno):
    navegador.login(alumno.correo)
    assert navegador.enviar(ENROLAR).status_code == 403
    assert navegador.enviar(CONFIRMAR, {"codigo": "123456"}).status_code == 403


@pytest.mark.django_db
def test_sin_sesion_no_se_puede_enrolar(navegador):
    assert navegador.enviar(ENROLAR).status_code == 401
    assert navegador.enviar(CONFIRMAR, {"codigo": "123456"}).status_code == 401


@pytest.mark.django_db
def test_el_enrolamiento_exige_csrf(navegador, docente_listo):
    navegador.login(docente_listo.correo)
    assert navegador.enviar(ENROLAR, con_csrf=False).status_code == 403


@pytest.mark.django_db
def test_pedir_otro_qr_reemplaza_el_secreto_pendiente(navegador, docente_listo):
    navegador.login(docente_listo.correo)
    viejo = _enrolar(navegador)
    nuevo = _enrolar(navegador)
    assert viejo.secret != nuevo.secret
    assert navegador.enviar(CONFIRMAR, {"codigo": viejo.now()}).status_code == 400
    assert navegador.enviar(CONFIRMAR, {"codigo": nuevo.now()}).status_code == 200


@pytest.mark.django_db
def test_confirmar_con_un_codigo_valido_activa_el_2fa(navegador, docente_listo):
    otra = Navegador()
    otra.login(docente_listo.correo)
    navegador.login(docente_listo.correo)
    totp = _enrolar(navegador)
    respuesta = navegador.enviar(CONFIRMAR, {"codigo": totp.now()})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo["paso"], cuerpo["debe_cambiar_password"]) == ("listo", False)

    # 8 códigos de recuperación, legibles y distintos, entregados una vez.
    codigos = cuerpo["codigos_recuperacion"]
    assert len(set(codigos)) == 8
    assert all(len(c) == 11 and c[5] == "-" for c in codigos)

    docente_listo.refresh_from_db()
    assert docente_listo.mfa_habilitado is True
    # Este navegador queda con una sesión completa; la otra restringida se cerró.
    assert _yo_alcance(navegador) == Alcance.COMPLETA
    assert navegador.get("/api/auth/yo").json()["pendientes"]["enrolar_mfa"] is False
    assert otra.get("/api/auth/yo").status_code == 401
    assert RegistroAuditoria.objects.filter(accion=Accion.MFA_ACTIVADO).count() == 1


def _yo_alcance(navegador):
    from rest_framework_simplejwt.tokens import AccessToken

    return AccessToken(navegador.cookies[ACCESO].value)[CLAIM_ALCANCE]


@pytest.mark.django_db
def test_confirmar_con_un_codigo_incorrecto_no_activa_y_queda_registrado(
    navegador, docente_listo
):
    navegador.login(docente_listo.correo)
    _enrolar(navegador)
    respuesta = navegador.enviar(CONFIRMAR, {"codigo": "000000"})
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "codigo_invalido"
    docente_listo.refresh_from_db()
    assert docente_listo.mfa_habilitado is False
    # El registro sobrevive al error (no queda dentro de una transacción deshecha).
    fallo = RegistroAuditoria.objects.get(accion=Accion.MFA_FALLIDO)
    assert fallo.detalle == {"etapa": "enrolamiento"}


@pytest.mark.django_db
def test_confirmar_sin_haber_pedido_el_qr(navegador, docente_listo):
    navegador.login(docente_listo.correo)
    respuesta = navegador.enviar(CONFIRMAR, {"codigo": "123456"})
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "enrolamiento_no_iniciado"


@pytest.mark.django_db
def test_no_se_puede_enrolar_de_nuevo_con_el_2fa_activo(navegador, docente_listo):
    navegador.login(docente_listo.correo)
    totp = _enrolar(navegador)
    navegador.enviar(CONFIRMAR, {"codigo": totp.now()})
    respuesta = navegador.enviar(ENROLAR)
    assert respuesta.status_code == 409
    assert respuesta.json()["codigo"] == "mfa_ya_activado"


@pytest.mark.django_db
def test_los_codigos_de_recuperacion_se_guardan_con_argon2id(navegador, docente_listo):
    navegador.login(docente_listo.correo)
    totp = _enrolar(navegador)
    codigos = navegador.enviar(CONFIRMAR, {"codigo": totp.now()}).json()["codigos_recuperacion"]
    guardados = CodigoRecuperacion.objects.filter(usuario=docente_listo)
    assert guardados.count() == 8
    for guardado in guardados:
        assert guardado.codigo_hash.startswith("argon2$argon2id$")
        assert all(c.replace("-", "") not in guardado.codigo_hash for c in codigos)


# --- Verificación: ticket -------------------------------------------------------


@pytest.mark.django_db
def test_el_login_del_personal_con_2fa_entrega_solo_un_ticket():
    persona, _ = _con_2fa()
    navegador = Navegador()
    respuesta = navegador.login(persona.correo)
    assert respuesta.json() == {"paso": "mfa"}
    assert ACCESO not in respuesta.cookies
    assert REFRESCO not in respuesta.cookies
    ticket = respuesta.cookies[TICKET]
    assert ticket["httponly"] is True
    assert ticket["secure"] is True
    assert ticket["samesite"] == "Strict"
    assert ticket["path"] == "/api/auth/mfa/"
    assert ticket["max-age"] == 300
    assert navegador.get("/api/auth/yo").status_code == 401


@pytest.mark.django_db
def test_sin_ticket_la_verificacion_responde_401(navegador):
    respuesta = _verificar(navegador, "123456")
    assert respuesta.status_code == 401
    assert respuesta.json()["codigo"] == "ticket_invalido"


@pytest.mark.django_db
def test_un_ticket_falsificado_no_sirve():
    persona, totp = _con_2fa()
    navegador = _iniciar(persona)
    navegador.cookies[TICKET] = navegador.cookies[TICKET].value[:-2] + "xx"
    assert _verificar(navegador, totp.now()).status_code == 401


@pytest.mark.django_db
def test_el_ticket_vence_a_los_5_minutos():
    persona, totp = _con_2fa()
    inicio = timezone.now()
    with time_machine.travel(inicio, tick=False):
        navegador = _iniciar(persona)
    with time_machine.travel(inicio + timedelta(minutes=5, seconds=1), tick=False):
        respuesta = _verificar(navegador, totp.now())
        assert respuesta.status_code == 401
        assert respuesta.json()["codigo"] == "ticket_invalido"


@pytest.mark.django_db
def test_el_ticket_sirve_una_sola_vez():
    persona, totp = _con_2fa()
    navegador = _iniciar(persona)
    ticket = navegador.cookies[TICKET].value
    assert _verificar(navegador, totp.now()).status_code == 200
    copia = Navegador()
    copia.cookies[TICKET] = ticket
    with time_machine.travel(timezone.now() + timedelta(seconds=31), tick=False):
        assert _verificar(copia, totp.now()).status_code == 401


@pytest.mark.django_db
def test_cambiar_la_contrasena_invalida_los_tickets_emitidos():
    persona, totp = _con_2fa()
    navegador = _iniciar(persona)
    persona.cerrar_todas_las_sesiones()
    persona.save(update_fields=["version_sesion"])
    assert _verificar(navegador, totp.now()).status_code == 401


@pytest.mark.django_db
def test_la_verificacion_exige_csrf():
    persona, totp = _con_2fa()
    navegador = _iniciar(persona)
    assert _verificar(navegador, totp.now(), con_csrf=False).status_code == 403


# --- Verificación: código válido, repetido y vencido --------------------------


@pytest.mark.django_db
def test_un_codigo_valido_entrega_la_sesion_completa():
    persona, totp = _con_2fa()
    navegador = _iniciar(persona)
    csrf_antes = navegador.cookies["csrftoken"].value
    respuesta = _verificar(navegador, totp.now())
    assert respuesta.status_code == 200
    assert respuesta.json() == {"paso": "listo", "debe_cambiar_password": False}
    assert respuesta.cookies[TICKET].value == ""
    assert navegador.cookies["csrftoken"].value != csrf_antes
    assert _yo_alcance(navegador) == Alcance.COMPLETA
    assert navegador.get("/api/auth/yo").status_code == 200
    registro = RegistroAuditoria.objects.get(accion=Accion.MFA_OK)
    assert registro.actor == persona
    assert registro.detalle == {"metodo": "totp"}


@pytest.mark.django_db
def test_un_codigo_ya_usado_no_sirve_de_nuevo():
    persona, totp = _con_2fa()
    codigo = totp.now()
    assert _verificar(_iniciar(persona), codigo).status_code == 200
    # Mismo código, otro inicio de sesión dentro del mismo intervalo.
    respuesta = _verificar(_iniciar(persona), codigo)
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "codigo_invalido"


@pytest.mark.django_db
def test_un_codigo_anterior_al_ultimo_usado_tampoco_sirve():
    persona, totp = _con_2fa()
    ahora = time.time()
    anterior = totp.at(ahora - 30)
    assert _verificar(_iniciar(persona), totp.at(ahora)).status_code == 200
    assert _verificar(_iniciar(persona), anterior).status_code == 400


@pytest.mark.django_db
def test_un_codigo_vencido_no_sirve():
    persona, totp = _con_2fa()
    with time_machine.travel(timezone.now(), tick=False):
        vencido = totp.at(time.time() - 90)
        respuesta = _verificar(_iniciar(persona), vencido)
    assert respuesta.status_code == 400
    assert respuesta.json()["codigo"] == "codigo_invalido"


@pytest.mark.django_db
@pytest.mark.parametrize("desfase", [-30, 30])
def test_se_acepta_un_reloj_desfasado_en_un_intervalo(desfase):
    persona, totp = _con_2fa()
    with time_machine.travel(timezone.now(), tick=False):
        assert _verificar(_iniciar(persona), totp.at(time.time() + desfase)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("codigo", ["", "12345", "1234567", "abcdef", "12 34 56x"])
def test_un_codigo_con_formato_invalido_no_sirve(codigo):
    persona, _ = _con_2fa()
    assert _verificar(_iniciar(persona), codigo).status_code == 400


# --- Verificación: límites y bloqueo -------------------------------------------


@pytest.mark.django_db
def test_cinco_intentos_por_ticket_y_el_sexto_responde_429():
    persona, _ = _con_2fa()
    navegador = _iniciar(persona)
    for _ in range(5):
        assert _verificar(navegador, "000000").status_code == 400
    respuesta = _verificar(navegador, "000000")
    assert respuesta.status_code == 429
    assert int(respuesta["Retry-After"]) <= 301


@pytest.mark.django_db
def test_los_codigos_incorrectos_suman_al_bloqueo_de_la_cuenta():
    persona, totp = _con_2fa()
    for _ in range(4):
        assert _verificar(_iniciar(persona), "000000").status_code == 400
    persona.refresh_from_db()
    # Volver a escribir la contraseña correcta no reinicia el contador.
    assert persona.intentos_fallidos == 4
    assert _verificar(_iniciar(persona), "000000").status_code == 400
    persona.refresh_from_db()
    assert persona.esta_bloqueado()
    assert RegistroAuditoria.objects.filter(accion=Accion.CUENTA_BLOQUEADA).count() == 1
    assert RegistroAuditoria.objects.filter(accion=Accion.MFA_FALLIDO).count() == 5


@pytest.mark.django_db
def test_durante_el_bloqueo_un_codigo_correcto_responde_igual_que_uno_incorrecto():
    persona, totp = _con_2fa()
    navegador = _iniciar(persona)
    Usuario.objects.filter(pk=persona.pk).update(
        bloqueado_hasta=timezone.now() + timedelta(minutes=15)
    )
    correcto = _verificar(navegador, totp.now())
    incorrecto = _verificar(navegador, "000000")
    assert (correcto.status_code, correcto.content) == (incorrecto.status_code, incorrecto.content)
    assert ACCESO not in correcto.cookies


@pytest.mark.django_db
def test_un_ingreso_completo_reinicia_el_contador():
    persona, totp = _con_2fa()
    _verificar(_iniciar(persona), "000000")
    assert _verificar(_iniciar(persona), totp.now()).status_code == 200
    persona.refresh_from_db()
    assert persona.intentos_fallidos == 0


# --- Códigos de recuperación ----------------------------------------------------


@pytest.fixture
def enrolado(db):
    """Docente que activó el 2FA por la API. Devuelve la cuenta, el TOTP y sus códigos."""
    persona = crear_usuario("docente.recupera@aulaconecta.cl", Rol.DOCENTE)
    Usuario.objects.filter(pk=persona.pk).update(debe_cambiar_password=False)
    navegador = Navegador()
    navegador.login(persona.correo)
    totp = _enrolar(navegador)
    codigos = navegador.enviar(CONFIRMAR, {"codigo": totp.now()}).json()["codigos_recuperacion"]
    return persona, totp, codigos


def test_un_codigo_de_recuperacion_entrega_la_sesion_y_sirve_una_sola_vez(enrolado):
    persona, _, codigos = enrolado
    respuesta = _verificar(_iniciar(persona), codigos[0])
    assert respuesta.status_code == 200
    assert respuesta.json()["codigos_restantes"] == 7
    registro = RegistroAuditoria.objects.filter(accion=Accion.MFA_OK).get()
    assert registro.detalle == {"metodo": "recuperacion", "recuperacion_restantes": 7}
    assert _verificar(_iniciar(persona), codigos[0]).status_code == 400


def test_el_codigo_de_recuperacion_se_acepta_sin_guion_y_en_minusculas(enrolado):
    persona, _, codigos = enrolado
    escrito = codigos[1].replace("-", " ").lower()
    assert _verificar(_iniciar(persona), escrito).status_code == 200


def test_un_codigo_de_recuperacion_inventado_no_sirve(enrolado):
    persona, _, _ = enrolado
    assert _verificar(_iniciar(persona), "ABCDE-FGHJK").status_code == 400


def test_la_bitacora_nunca_guarda_codigos(enrolado):
    persona, totp, codigos = enrolado
    with time_machine.travel(timezone.now() + timedelta(seconds=31), tick=False):
        actual = totp.now()
        _verificar(_iniciar(persona), actual)
    _verificar(_iniciar(persona), codigos[2])
    _verificar(_iniciar(persona), "000000")
    for registro in RegistroAuditoria.objects.all():
        texto = str(registro.detalle)
        assert actual not in texto
        assert "000000" not in texto
        assert all(c not in texto and c.replace("-", "") not in texto for c in codigos)


# --- Peticiones simultáneas -----------------------------------------------------


def test_el_mismo_codigo_enviado_a_la_vez_solo_sirve_una_vez(bd_con_transacciones):
    persona, totp = _con_2fa("docente.simultaneo@aulaconecta.cl")
    # Dos inicios de sesión distintos con su propio ticket, el mismo código.
    tickets = [leer_ticket(_iniciar(persona).cookies[TICKET].value) for _ in range(2)]
    codigo = totp.now()
    barrera = threading.Barrier(2)
    resultados = []

    def intentar(ticket):
        try:
            barrera.wait(timeout=30)
            verificar_segundo_factor(ticket, codigo)
            resultados.append("ok")
        except ErrorApi as error:
            resultados.append(error.codigo)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=intentar, args=(t,)) for t in tickets]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=60)
    assert sorted(resultados) == ["codigo_invalido", "ok"]
