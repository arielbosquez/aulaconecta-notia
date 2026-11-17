import uuid

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower

from .managers import UsuarioManager, normalizar_correo


class Rol(models.TextChoices):
    ALUMNO = "ALUMNO", "Alumno"
    DOCENTE = "DOCENTE", "Docente"
    ADMIN = "ADMIN", "Administrador"


# Roles que trabajan en el colegio: contraseña más larga y 2FA obligatorio.
ROLES_DEL_PERSONAL = frozenset({Rol.DOCENTE, Rol.ADMIN})


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Persona que usa NotIA: alumno, docente o administrador.

    Es el modelo de usuario del proyecto (AUTH_USER_MODEL) desde la primera
    migración.

    Por minimización de datos (Ley 21.719) no se guarda RUT, fecha de
    nacimiento, dirección, teléfono ni datos de salud.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correo = models.EmailField("correo institucional", max_length=254, unique=True)
    nombres = models.CharField(max_length=80)
    apellidos = models.CharField(max_length=80)
    # Por omisión, el rol con menos permisos.
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.ALUMNO)
    is_active = models.BooleanField("activo", default=True)

    # --- Contraseña y bloqueo ---
    # Las cuentas nuevas parten con una contraseña temporal que hay que cambiar.
    debe_cambiar_password = models.BooleanField("debe cambiar la contraseña", default=True)
    intentos_fallidos = models.PositiveSmallIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    # --- Sesiones ---
    # Viaja en cada token (claim "ver"). Al incrementarla, todos los tokens
    # emitidos antes dejan de valer: así se cierran todas las sesiones.
    version_sesion = models.PositiveIntegerField("versión de sesión", default=1)
    ultimo_acceso = models.DateTimeField("último acceso", null=True, blank=True)

    # --- Segundo factor (docentes y administradores) ---
    mfa_habilitado = models.BooleanField("2FA habilitado", default=False)
    # Secreto TOTP cifrado con Fernet (MFA_ENCRYPTION_KEY); nunca en texto plano.
    mfa_secreto_cifrado = models.TextField(blank=True)
    # Último intervalo TOTP aceptado, para rechazar un código repetido.
    mfa_ultimo_paso = models.BigIntegerField(null=True, blank=True)

    voz_preferida = models.CharField(max_length=60, blank=True)

    # --- Consentimiento del apoderado (solo alumnos) ---
    # El documento firmado lo custodia el colegio; aquí queda quién lo
    # verificó y cuándo. Sin esto, la cuenta de un alumno no puede ingresar.
    consentimiento_verificado_en = models.DateTimeField(null=True, blank=True)
    consentimiento_verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="consentimientos_verificados",
    )

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
            models.CheckConstraint(
                condition=models.Q(rol__in=Rol.values),
                name="usuario_rol_conocido",
            ),
            # El consentimiento se registra completo: fecha y quién lo verificó.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        consentimiento_verificado_en__isnull=True,
                        consentimiento_verificado_por__isnull=True,
                    )
                    | models.Q(
                        consentimiento_verificado_en__isnull=False,
                        consentimiento_verificado_por__isnull=False,
                    )
                ),
                name="usuario_consentimiento_completo",
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

    @property
    def es_del_personal(self) -> bool:
        """Docente o administrador: contraseña más larga y 2FA obligatorio."""
        return self.rol in ROLES_DEL_PERSONAL

    @property
    def tiene_consentimiento(self) -> bool:
        return self.consentimiento_verificado_en is not None

    def cerrar_todas_las_sesiones(self) -> None:
        """Invalida todos los tokens emitidos. Quien llama guarda el cambio."""
        self.version_sesion += 1
