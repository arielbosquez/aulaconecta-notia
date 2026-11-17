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
