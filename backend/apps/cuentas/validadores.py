"""Validadores de contraseña propios de NotIA (RS-01)."""

from django.conf import settings
from django.core.exceptions import ValidationError


class LargoMinimoPorRol:
    """Exige un largo mínimo según el rol de la cuenta.

    Docentes y administradores usan contraseñas más largas que los alumnos,
    porque sus cuentas dan acceso a los datos de todo un curso. Si no se sabe
    de quién es la contraseña, se aplica el largo más exigente.
    """

    def _largo_minimo(self, usuario) -> int:
        if usuario is not None and not getattr(usuario, "es_del_personal", True):
            return settings.PASSWORD_LARGO_MINIMO_ALUMNO
        return settings.PASSWORD_LARGO_MINIMO_PERSONAL

    def validate(self, password: str, user=None) -> None:
        minimo = self._largo_minimo(user)
        if len(password) < minimo:
            raise ValidationError(
                "La contraseña debe tener al menos %(minimo)d caracteres.",
                code="password_muy_corta",
                params={"minimo": minimo},
            )

    def get_help_text(self) -> str:
        return (
            f"La contraseña debe tener al menos {settings.PASSWORD_LARGO_MINIMO_ALUMNO} "
            f"caracteres para alumnos y {settings.PASSWORD_LARGO_MINIMO_PERSONAL} para "
            "docentes y administradores."
        )
