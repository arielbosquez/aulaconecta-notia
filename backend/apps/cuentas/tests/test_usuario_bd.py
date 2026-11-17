"""Pruebas del modelo Usuario contra PostgreSQL: valores por omisión y restricciones."""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar
from apps.cuentas.models import Rol, Usuario

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return Usuario.objects.create_user(
        "admin.demo@aulaconecta.cl", rol=Rol.ADMIN, nombres="Admin", apellidos="Demo"
    )


@pytest.fixture
def alumno():
    return Usuario.objects.create_user(
        "alumno.demo@aulaconecta.cl", nombres="Alumno", apellidos="Demo"
    )


def test_una_cuenta_nueva_parte_con_los_valores_mas_restrictivos(alumno):
    guardado = Usuario.objects.get(pk=alumno.pk)
    assert guardado.rol == Rol.ALUMNO
    assert guardado.es_del_personal is False
    assert guardado.debe_cambiar_password is True
    assert guardado.tiene_consentimiento is False
    assert guardado.mfa_habilitado is False
    assert guardado.mfa_secreto_cifrado == ""
    assert guardado.intentos_fallidos == 0
    assert guardado.bloqueado_hasta is None
    assert guardado.version_sesion == 1
    assert guardado.ultimo_acceso is None
    assert guardado.is_superuser is False


def test_docentes_y_administradores_son_personal(admin):
    assert admin.es_del_personal is True
    assert Usuario(rol=Rol.DOCENTE).es_del_personal is True


def test_un_superusuario_siempre_es_administrador():
    usuario = Usuario.objects.create_superuser(
        "otro.admin.demo@aulaconecta.cl", "clave-ficticia-de-prueba", rol=Rol.ALUMNO
    )
    assert usuario.rol == Rol.ADMIN


def test_la_base_rechaza_un_rol_desconocido(alumno):
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.filter(pk=alumno.pk).update(rol="DIRECTOR")


def test_el_consentimiento_se_registra_con_fecha_y_responsable(alumno, admin):
    alumno.consentimiento_verificado_en = timezone.now()
    alumno.consentimiento_verificado_por = admin
    alumno.save()
    assert Usuario.objects.get(pk=alumno.pk).tiene_consentimiento is True


def test_la_base_rechaza_un_consentimiento_a_medias(alumno, admin):
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.filter(pk=alumno.pk).update(consentimiento_verificado_en=timezone.now())
    with pytest.raises(IntegrityError), transaction.atomic():
        Usuario.objects.filter(pk=alumno.pk).update(consentimiento_verificado_por=admin)


def test_no_se_puede_borrar_a_quien_verifico_un_consentimiento(alumno, admin):
    Usuario.objects.filter(pk=alumno.pk).update(
        consentimiento_verificado_en=timezone.now(), consentimiento_verificado_por=admin
    )
    with pytest.raises(ProtectedError):
        admin.delete()


def test_cerrar_todas_las_sesiones_sube_la_version(alumno):
    alumno.cerrar_todas_las_sesiones()
    alumno.save(update_fields=["version_sesion"])
    assert Usuario.objects.get(pk=alumno.pk).version_sesion == 2


def test_la_bitacora_copia_el_rol_del_actor(admin):
    registro = registrar(Accion.USUARIO_CREADO, actor=admin)
    Usuario.objects.filter(pk=admin.pk).update(rol=Rol.DOCENTE)
    registro.refresh_from_db()
    assert registro.rol_actor == "ADMIN"
