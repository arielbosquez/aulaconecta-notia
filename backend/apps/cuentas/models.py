import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower

from .managers import UsuarioManager, normalizar_correo


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Persona que usa NotIA: alumno, docente o administrador.

    Es el modelo de usuario del proyecto (AUTH_USER_MODEL) desde la primera
    migración. En la Fase 1 se completa con el rol y los campos de bloqueo,
    sesión, 2FA y consentimiento.

    Por minimización de datos (Ley 21.719) no se guarda RUT, fecha de
    nacimiento, dirección, teléfono ni datos de salud.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correo = models.EmailField("correo institucional", max_length=254, unique=True)
    nombres = models.CharField(max_length=80)
    apellidos = models.CharField(max_length=80)
    is_active = models.BooleanField("activo", default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "correo"
    EMAIL_FIELD = "correo"
    REQUIRED_FIELDS = ["nombres", "apellidos"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [
            # El correo se guarda siempre en minúsculas; la base de datos lo garantiza.
            models.CheckConstraint(
                condition=models.Q(correo=Lower("correo")),
                name="usuario_correo_en_minusculas",
            ),
        ]

    def __str__(self) -> str:
        return self.nombre_completo

    def save(self, *args, **kwargs):
        self.correo = normalizar_correo(self.correo)
        super().save(*args, **kwargs)

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}".strip()
