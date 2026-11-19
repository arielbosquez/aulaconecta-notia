"""Permisos de la API según el estado de la sesión (sección 10 de la arquitectura)."""

from rest_framework.permissions import BasePermission

from .tokens import Alcance


def alcance_de(request) -> Alcance | None:
    """Alcance de la sesión con que llegó la petición, si tiene una."""
    return getattr(request, "alcance", None)


class SesionCompleta(BasePermission):
    """Exige una sesión sin pasos pendientes.

    Es el permiso por omisión de toda la API. Quedan fuera las sesiones
    restringidas (un docente o administrador que aún no activa su 2FA) y las
    cuentas que todavía deben cambiar su contraseña temporal. Los pocos
    endpoints que esas sesiones sí pueden usar lo declaran de forma explícita.
    """

    def has_permission(self, request, view) -> bool:
        usuario = request.user
        return bool(
            usuario
            and usuario.is_authenticated
            and alcance_de(request) is Alcance.COMPLETA
            and not usuario.debe_cambiar_password
        )


class EsAlumno(BasePermission):
    """Solo alumnos (sección 10). Se usa junto con ``SesionCompleta``.

    Un docente o administrador que llama a un endpoint del alumno recibe 403
    y queda en la bitácora (con límite de frecuencia). El administrador no
    rinde pruebas ni ve las respuestas de los alumnos.
    """

    def has_permission(self, request, view) -> bool:
        from apps.auditoria.servicios import registrar_acceso_denegado

        from .models import Rol

        usuario = request.user
        if not (usuario and usuario.is_authenticated):
            return False
        if usuario.rol == Rol.ALUMNO:
            return True
        registrar_acceso_denegado(request, motivo="rol_no_permitido")
        return False


PERMISOS_DEL_ALUMNO = [SesionCompleta, EsAlumno]
