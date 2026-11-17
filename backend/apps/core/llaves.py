"""Generación y validación de las llaves de NotIA.

Hay tres llaves, siempre distintas entre sí:

- ``DJANGO_SECRET_KEY``: firmas internas de Django.
- ``JWT_SIGNING_KEY``: firma de los tokens de sesión.
- ``MFA_ENCRYPTION_KEY``: cifrado (Fernet) de los secretos de 2FA.

Este módulo no importa nada de Django que dependa de los settings, porque
los propios settings lo usan.
"""

import base64
import binascii
import secrets

from django.core.exceptions import ImproperlyConfigured

# Django advierte (security.W009) si la llave tiene menos de 50 caracteres.
LARGO_MINIMO_LLAVE = 50
# Una llave Fernet son 32 bytes aleatorios codificados en base64 para URL.
BYTES_LLAVE_FERNET = 32


def nueva_llave_secreta() -> str:
    """Devuelve una llave aleatoria de 86 caracteres (64 bytes de entropía)."""
    return secrets.token_urlsafe(64)


def nueva_llave_fernet() -> str:
    """Devuelve una llave con el formato que exige Fernet."""
    return base64.urlsafe_b64encode(secrets.token_bytes(BYTES_LLAVE_FERNET)).decode("ascii")


def es_llave_fernet(valor: str) -> bool:
    """Comprueba el formato de una llave Fernet sin revelar su contenido."""
    try:
        return len(base64.b64decode(valor, altchars=b"-_", validate=True)) == BYTES_LLAVE_FERNET
    except (binascii.Error, ValueError):
        return False


def validar_llaves(*, secreta: str, jwt: str, mfa: str) -> None:
    """Detiene el arranque si alguna llave es débil, repetida o mal formada.

    Los mensajes nombran la variable, nunca su valor.
    """
    for nombre, valor in (("DJANGO_SECRET_KEY", secreta), ("JWT_SIGNING_KEY", jwt)):
        if len(valor) < LARGO_MINIMO_LLAVE or len(set(valor)) < 10:
            raise ImproperlyConfigured(
                f"{nombre} es demasiado corta o predecible. "
                "Genera una nueva con: python manage.py generar_llaves"
            )
    if not es_llave_fernet(mfa):
        raise ImproperlyConfigured(
            "MFA_ENCRYPTION_KEY no tiene el formato de una llave Fernet. "
            "Genera una nueva con: python manage.py generar_llaves"
        )
    if len({secreta, jwt, mfa}) < 3:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY, JWT_SIGNING_KEY y MFA_ENCRYPTION_KEY deben ser distintas entre sí."
        )
