"""Pantallas de acceso en un navegador real contra el backend real (PR 1.6).

Cubren el login del alumno, el login del docente con 2FA, el cambio de la
contraseña temporal con la activación del 2FA, la redirección a /ingresar de
toda página protegida sin sesión, y que no haya errores de CSP (lo revisa el
fixture ``pagina`` al final de cada prueba).
"""

import re

import pyotp
import pytest
from django.utils import timezone
from playwright.sync_api import Page, expect

from apps.cuentas.mfa import guardar_secreto
from apps.cuentas.models import Rol, Usuario

pytestmark = pytest.mark.e2e

# Contraseñas ficticias, solo para estas pruebas.
CLAVE = "Ferrocarril-Azul-77"
NUEVA = "Glaciar-Naranjo-58"
GENERICO = "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente."

PROTEGIDAS = ["/", "/cambiar-clave/", "/seguridad/2fa/"]


def _admin():
    return Usuario.objects.create_user(
        "admin.e2e@aulaconecta.cl", CLAVE, nombres="Admin", apellidos="Demo", rol=Rol.ADMIN
    )


def _alumno(*, temporal=False):
    return Usuario.objects.create_user(
        "alumno.demo@aulaconecta.cl",
        CLAVE,
        nombres="Alumno",
        apellidos="Demo",
        rol=Rol.ALUMNO,
        debe_cambiar_password=temporal,
        consentimiento_verificado_en=timezone.now(),
        consentimiento_verificado_por=_admin(),
    )


def _docente(*, temporal=False, con_2fa=False):
    docente = Usuario.objects.create_user(
        "docente.demo@aulaconecta.cl",
        CLAVE,
        nombres="Docente",
        apellidos="Demo",
        rol=Rol.DOCENTE,
        debe_cambiar_password=temporal,
    )
    totp = None
    if con_2fa:
        secreto = pyotp.random_base32()
        guardar_secreto(docente, secreto)
        docente.mfa_habilitado = True
        docente.save(update_fields=["mfa_secreto_cifrado", "mfa_habilitado"])
        totp = pyotp.TOTP(secreto)
    return docente, totp


def _ingresar(pagina: Page, servidor: str, correo: str, clave: str = CLAVE) -> None:
    pagina.goto(f"{servidor}/ingresar/")
    pagina.get_by_label("Correo institucional").fill(correo)
    pagina.get_by_label("Contraseña", exact=True).fill(clave)
    pagina.get_by_role("button", name="Ingresar").click()


# --- Páginas protegidas -----------------------------------------------------------


@pytest.mark.parametrize("ruta", PROTEGIDAS)
def test_una_pagina_protegida_sin_sesion_redirige_a_ingresar(pagina, servidor, ruta):
    pagina.goto(f"{servidor}{ruta}")
    pagina.wait_for_url(f"{servidor}/ingresar/")
    expect(pagina.get_by_role("heading", name="Ingresar")).to_be_visible()


def test_el_aviso_de_privacidad_es_publico(pagina, servidor):
    pagina.goto(f"{servidor}/ingresar/")
    pagina.get_by_role("link", name="Aviso de privacidad").click()
    pagina.wait_for_url(f"{servidor}/privacidad/")
    expect(pagina.get_by_role("heading", name="Aviso de privacidad")).to_be_visible()


# --- Login del alumno -------------------------------------------------------------


def test_login_de_alumno_y_cierre_de_sesion(pagina, servidor):
    _alumno()
    _ingresar(pagina, servidor, "alumno.demo@aulaconecta.cl")
    pagina.wait_for_url(f"{servidor}/")
    expect(pagina.get_by_role("heading", name="Hola, Alumno Demo")).to_be_visible()
    # El JavaScript no ve los tokens: solo la cookie CSRF es legible.
    cookies_visibles = pagina.evaluate("document.cookie")
    assert "notia_acceso" not in cookies_visibles
    assert "notia_refresco" not in cookies_visibles

    pagina.get_by_role("button", name="Cerrar sesión").click()
    pagina.wait_for_url(f"{servidor}/ingresar/")
    pagina.goto(f"{servidor}/")
    pagina.wait_for_url(f"{servidor}/ingresar/")


def test_credenciales_incorrectas_muestran_el_mensaje_generico(pagina, servidor):
    _alumno()
    _ingresar(pagina, servidor, "alumno.demo@aulaconecta.cl", "otra-clave-cualquiera")
    expect(pagina.get_by_role("alert")).to_contain_text(GENERICO)
    expect(pagina.get_by_label("Contraseña", exact=True)).to_have_value("")
    # Lo mismo con un correo que no existe.
    pagina.get_by_label("Contraseña", exact=True).fill(CLAVE)
    pagina.get_by_label("Correo institucional").fill("nadie.demo@aulaconecta.cl")
    pagina.get_by_role("button", name="Ingresar").click()
    expect(pagina.get_by_role("alert")).to_contain_text(GENERICO)


def test_los_campos_parten_vacios_y_la_contrasena_se_puede_mostrar(pagina, servidor):
    pagina.goto(f"{servidor}/ingresar/")
    correo = pagina.get_by_label("Correo institucional")
    clave = pagina.get_by_label("Contraseña", exact=True)
    expect(correo).to_have_value("")
    expect(clave).to_have_value("")
    expect(correo).to_be_focused()

    clave.fill(CLAVE)
    expect(clave).to_have_attribute("type", "password")
    pagina.get_by_role("button", name="Mostrar contraseña").click()
    expect(clave).to_have_attribute("type", "text")
    pagina.get_by_role("button", name="Ocultar contraseña").click()
    expect(clave).to_have_attribute("type", "password")


def test_avisa_si_bloq_mayus_esta_activado(pagina, servidor):
    pagina.goto(f"{servidor}/ingresar/")
    clave = pagina.get_by_label("Contraseña", exact=True)
    clave.dispatch_event("keydown", {"key": "A", "modifierCapsLock": True})
    expect(pagina.get_by_text("Bloq Mayús está activado.")).to_be_visible()
    clave.dispatch_event("keyup", {"key": "a", "modifierCapsLock": False})
    expect(pagina.get_by_text("Bloq Mayús está activado.")).to_be_hidden()


# --- Login del docente con 2FA ----------------------------------------------------


def test_login_de_docente_con_2fa(pagina, servidor):
    _, totp = _docente(con_2fa=True)
    _ingresar(pagina, servidor, "docente.demo@aulaconecta.cl")

    # El paso 2 reemplaza a la tarjeta del paso 1.
    expect(pagina.get_by_text("Paso 2 de 2")).to_be_visible()
    expect(pagina.get_by_role("heading", name="Segundo factor")).to_be_visible()
    expect(pagina.get_by_label("Correo institucional")).to_have_count(0)

    # Volver lleva al paso 1, y se puede ingresar de nuevo.
    pagina.get_by_role("button", name="Volver").click()
    expect(pagina.get_by_role("heading", name="Ingresar")).to_be_visible()
    pagina.get_by_label("Contraseña", exact=True).fill(CLAVE)
    pagina.get_by_role("button", name="Ingresar").click()

    pagina.get_by_role("textbox", name="Código", exact=True).fill("000000")
    pagina.get_by_role("button", name="Verificar").click()
    expect(pagina.get_by_role("alert")).to_contain_text("El código no es válido")

    pagina.get_by_role("textbox", name="Código", exact=True).fill(totp.now())
    pagina.get_by_role("button", name="Verificar").click()
    pagina.wait_for_url(f"{servidor}/")
    expect(pagina.get_by_role("heading", name="Hola, Docente Demo")).to_be_visible()


# --- Contraseña temporal y activación del 2FA -------------------------------------


def test_primer_ingreso_del_docente_cambia_la_clave_y_activa_el_2fa(pagina, servidor):
    _docente(temporal=True)
    _ingresar(pagina, servidor, "docente.demo@aulaconecta.cl")

    # Paso 1 de 2: la contraseña temporal.
    pagina.wait_for_url(f"{servidor}/cambiar-clave/")
    expect(pagina.get_by_text("Paso 1 de 2")).to_be_visible()
    expect(pagina.get_by_role("heading", name="Crea tu contraseña")).to_be_visible()
    pagina.get_by_label("Contraseña temporal").fill(CLAVE)
    pagina.get_by_role("button", name="Continuar").click()

    # Paso 2 de 2: la nueva, que reemplaza a la tarjeta anterior.
    expect(pagina.get_by_text("Paso 2 de 2")).to_be_visible()
    pagina.get_by_label("Contraseña nueva", exact=True).fill(NUEVA)
    pagina.get_by_label("Repite la contraseña nueva").fill(NUEVA)
    pagina.get_by_role("button", name="Guardar contraseña").click()

    # Activación del 2FA: QR generado en el servidor y la clave para escribir.
    pagina.wait_for_url(f"{servidor}/seguridad/2fa/")
    expect(pagina.get_by_text("Paso 1 de 3")).to_be_visible()
    qr = pagina.get_by_role("img", name="Código QR para tu aplicación de autenticación")
    expect(qr).to_have_attribute("src", re.compile(r"^data:image/svg\+xml"))
    secreto = pagina.get_by_label("Clave para escribir a mano").inner_text().replace(" ", "")
    pagina.get_by_role("button", name="Ya lo escaneé").click()

    expect(pagina.get_by_text("Paso 2 de 3")).to_be_visible()
    pagina.get_by_role("textbox", name="Código", exact=True).fill(pyotp.TOTP(secreto).now())
    pagina.get_by_role("button", name="Activar").click()

    expect(pagina.get_by_text("Paso 3 de 3")).to_be_visible()
    codigos = pagina.get_by_role("list", name="Códigos de recuperación").get_by_role("listitem")
    expect(codigos).to_have_count(8)
    continuar = pagina.get_by_role("button", name="Continuar")
    expect(continuar).to_be_disabled()
    pagina.get_by_label("Guardé mis códigos en un lugar seguro.").check()
    continuar.click()

    pagina.wait_for_url(f"{servidor}/")
    expect(pagina.get_by_role("heading", name="Hola, Docente Demo")).to_be_visible()
    docente = Usuario.objects.get(correo="docente.demo@aulaconecta.cl")
    assert docente.mfa_habilitado
    assert not docente.debe_cambiar_password


def test_cambio_de_contrasena_temporal_del_alumno_con_errores(pagina, servidor):
    _alumno(temporal=True)
    _ingresar(pagina, servidor, "alumno.demo@aulaconecta.cl")
    pagina.wait_for_url(f"{servidor}/cambiar-clave/")

    # Una contraseña temporal equivocada devuelve al paso 1 con el aviso.
    pagina.get_by_label("Contraseña temporal").fill("no-es-la-temporal")
    pagina.get_by_role("button", name="Continuar").click()
    pagina.get_by_label("Contraseña nueva", exact=True).fill(NUEVA)
    pagina.get_by_label("Repite la contraseña nueva").fill(NUEVA)
    pagina.get_by_role("button", name="Guardar contraseña").click()
    expect(pagina.get_by_text("Paso 1 de 2")).to_be_visible()
    expect(pagina.get_by_role("alert")).to_contain_text("La contraseña actual no es correcta")

    # Una nueva que no cumple la política muestra el motivo junto al campo.
    pagina.get_by_label("Contraseña temporal").fill(CLAVE)
    pagina.get_by_role("button", name="Continuar").click()
    pagina.get_by_label("Contraseña nueva", exact=True).fill("1234567890123")
    pagina.get_by_label("Repite la contraseña nueva").fill("1234567890123")
    pagina.get_by_role("button", name="Guardar contraseña").click()
    expect(pagina.get_by_text("completamente numérica")).to_be_visible()

    # Las dos deben coincidir.
    pagina.get_by_label("Contraseña nueva", exact=True).fill(NUEVA)
    pagina.get_by_label("Repite la contraseña nueva").fill(NUEVA + "x")
    pagina.get_by_role("button", name="Guardar contraseña").click()
    expect(pagina.get_by_text("Las dos contraseñas no coinciden.")).to_be_visible()

    pagina.get_by_label("Repite la contraseña nueva").fill(NUEVA)
    pagina.get_by_role("button", name="Guardar contraseña").click()
    pagina.wait_for_url(f"{servidor}/")
    expect(pagina.get_by_role("heading", name="Hola, Alumno Demo")).to_be_visible()
