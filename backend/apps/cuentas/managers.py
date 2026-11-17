from django.contrib.auth.base_user import BaseUserManager


def normalizar_correo(correo: str) -> str:
    """Deja el correo sin espacios alrededor y completamente en minúsculas."""
    return (correo or "").strip().lower()


class UsuarioManager(BaseUserManager):
    """Crea usuarios identificados por su correo institucional."""

    use_in_migrations = True

    def _crear(self, correo: str, password: str | None, **campos):
        correo = normalizar_correo(correo)
        if not correo:
            raise ValueError("El correo es obligatorio.")
        usuario = self.model(correo=correo, **campos)
        # set_password guarda solo el hash; con None la cuenta queda sin contraseña utilizable.
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, correo: str, password: str | None = None, **campos):
        campos["is_superuser"] = False
        return self._crear(correo, password, **campos)

    def create_superuser(self, correo: str, password: str | None = None, **campos):
        if not password:
            raise ValueError("Un superusuario necesita contraseña.")
        campos["is_superuser"] = True
        # El superusuario de Django es siempre un administrador de NotIA.
        campos["rol"] = "ADMIN"
        return self._crear(correo, password, **campos)

    def get_by_natural_key(self, correo: str):
        return self.get(correo=normalizar_correo(correo))
