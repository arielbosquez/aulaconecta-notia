from django.conf import settings
from django.db import models

LARGO_USER_AGENT = 200


class BitacoraInmutable(Exception):
    """Se intentó modificar o borrar un registro de la bitácora."""


class Accion(models.TextChoices):
    """Hechos que quedan en la bitácora (sección 6 de la arquitectura)."""

    # Autenticación
    LOGIN_OK = "LOGIN_OK", "Inicio de sesión correcto"
    LOGIN_FALLIDO = "LOGIN_FALLIDO", "Inicio de sesión fallido"
    CUENTA_BLOQUEADA = "CUENTA_BLOQUEADA", "Cuenta bloqueada"
    CUENTA_DESBLOQUEADA = "CUENTA_DESBLOQUEADA", "Cuenta desbloqueada"
    MFA_OK = "MFA_OK", "Segundo factor correcto"
    MFA_FALLIDO = "MFA_FALLIDO", "Segundo factor fallido"
    MFA_ACTIVADO = "MFA_ACTIVADO", "Segundo factor activado"
    MFA_REINICIADO = "MFA_REINICIADO", "Segundo factor reiniciado"
    LOGOUT = "LOGOUT", "Cierre de sesión"
    PASSWORD_CAMBIADA = "PASSWORD_CAMBIADA", "Contraseña cambiada"
    PASSWORD_RESTABLECIDA = "PASSWORD_RESTABLECIDA", "Contraseña restablecida"
    ACCESO_DENEGADO = "ACCESO_DENEGADO", "Acceso denegado"
    # Usuarios
    USUARIO_CREADO = "USUARIO_CREADO", "Usuario creado"
    USUARIO_MODIFICADO = "USUARIO_MODIFICADO", "Usuario modificado"
    USUARIO_DESACTIVADO = "USUARIO_DESACTIVADO", "Usuario desactivado"
    CONSENTIMIENTO_REGISTRADO = "CONSENTIMIENTO_REGISTRADO", "Consentimiento registrado"
    # Evaluaciones
    EVALUACION_CREADA = "EVALUACION_CREADA", "Evaluación creada"
    EVALUACION_PUBLICADA = "EVALUACION_PUBLICADA", "Evaluación publicada"
    EVALUACION_VERSIONADA = "EVALUACION_VERSIONADA", "Evaluación versionada"
    EVALUACION_CERRADA = "EVALUACION_CERRADA", "Evaluación cerrada"
    MODALIDAD_ASIGNADA = "MODALIDAD_ASIGNADA", "Modalidad asignada"
    # Rendición y resultados
    INTENTO_INICIADO = "INTENTO_INICIADO", "Intento iniciado"
    INTENTO_FINALIZADO = "INTENTO_FINALIZADO", "Intento finalizado"
    INTENTO_REABIERTO = "INTENTO_REABIERTO", "Intento reabierto"
    PREGUNTA_ANULADA = "PREGUNTA_ANULADA", "Pregunta anulada"
    CORRECCION_MODIFICADA = "CORRECCION_MODIFICADA", "Corrección modificada"
    NOTAS_PUBLICADAS = "NOTAS_PUBLICADAS", "Notas publicadas"
    # Privacidad
    DATOS_EXPORTADOS = "DATOS_EXPORTADOS", "Datos exportados"
    ALUMNO_ANONIMIZADO = "ALUMNO_ANONIMIZADO", "Alumno anonimizado"
    DATOS_PURGADOS = "DATOS_PURGADOS", "Datos purgados"


class RegistroAuditoriaQuerySet(models.QuerySet):
    """Consultas de la bitácora: se puede leer y agregar, nada más."""

    def update(self, **campos):
        raise BitacoraInmutable("Los registros de la bitácora no se modifican.")

    def delete(self):
        raise BitacoraInmutable("Los registros de la bitácora no se borran.")


class RegistroAuditoria(models.Model):
    """Una línea de la bitácora de auditoría: quién hizo qué, cuándo y desde dónde.

    Solo se inserta y se lee. Hay dos barreras: este modelo rechaza las
    modificaciones, y el rol de base de datos de la aplicación (``notia_app``)
    no tiene UPDATE ni DELETE sobre la tabla, de modo que tampoco sirve
    saltarse el modelo con SQL directo.

    Nunca guarda contraseñas (ni las fallidas), tokens, códigos de 2FA,
    alternativas elegidas ni texto de preguntas. Los registros se crean con
    ``apps.auditoria.servicios.registrar``, que cuida esa regla.
    """

    id = models.BigAutoField(primary_key=True)
    ocurrido_en = models.DateTimeField("ocurrido en", auto_now_add=True)
    # PROTECT: una cuenta con historial no se borra, se desactiva o se anonimiza.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registros_auditoria",
    )
    # Copia del rol que tenía el actor en ese momento; vacío si no hay actor.
    rol_actor = models.CharField("rol del actor", max_length=10, blank=True)
    accion = models.CharField("acción", max_length=30, choices=Accion.choices)
    objeto_tipo = models.CharField("tipo de objeto", max_length=50, blank=True)
    objeto_id = models.CharField("identificador del objeto", max_length=64, blank=True)
    ip = models.GenericIPAddressField("dirección IP", null=True, blank=True)
    user_agent = models.CharField("navegador", max_length=LARGO_USER_AGENT, blank=True)
    detalle = models.JSONField(default=dict, blank=True)

    objects = RegistroAuditoriaQuerySet.as_manager()

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-ocurrido_en", "-id"]
        indexes = [
            # Filtros de la consulta del administrador (CU-16): fecha, acción y actor.
            models.Index(fields=["ocurrido_en"], name="auditoria_por_fecha"),
            models.Index(fields=["accion", "ocurrido_en"], name="auditoria_por_accion"),
            models.Index(fields=["actor", "ocurrido_en"], name="auditoria_por_actor"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(accion__in=Accion.values),
                name="auditoria_accion_conocida",
            ),
        ]

    def __str__(self) -> str:
        momento = f"{self.ocurrido_en:%d-%m-%Y %H:%M:%S}" if self.ocurrido_en else "sin guardar"
        return f"{self.accion} · {momento}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise BitacoraInmutable("Los registros de la bitácora no se modifican.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise BitacoraInmutable("Los registros de la bitácora no se borran.")
