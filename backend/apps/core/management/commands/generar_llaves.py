"""Comando ``python manage.py generar_llaves``."""

from django.core.management.base import BaseCommand

from apps.core.llaves import nueva_llave_fernet, nueva_llave_secreta


class Command(BaseCommand):
    help = (
        "Imprime valores aleatorios seguros para DJANGO_SECRET_KEY, JWT_SIGNING_KEY y "
        "MFA_ENCRYPTION_KEY. Solo los muestra en la terminal: no escribe ningún archivo."
    )
    # No necesita la base de datos ni las comprobaciones del proyecto.
    requires_system_checks = []
    requires_migrations_checks = False

    def handle(self, *args, **opciones):
        llaves = {
            "DJANGO_SECRET_KEY": nueva_llave_secreta(),
            "JWT_SIGNING_KEY": nueva_llave_secreta(),
            "MFA_ENCRYPTION_KEY": nueva_llave_fernet(),
        }

        # Las instrucciones van por la salida de error para que la salida
        # estándar tenga solo las tres líneas NOMBRE=valor.
        self.stderr.write(
            "Llaves nuevas para NotIA. Cópialas en backend/.env (desarrollo) o en "
            "Key Vault (producción).",
            style_func=self.style.NOTICE,
        )
        for nombre, valor in llaves.items():
            self.stdout.write(f"{nombre}={valor}")
        self.stderr.write(
            "No se guardaron en ningún archivo y no se volverán a mostrar. No las pegues "
            "en chats, commits ni capturas de pantalla. Cambiar MFA_ENCRYPTION_KEY deja "
            "inservibles los 2FA ya activados.",
            style_func=self.style.WARNING,
        )
