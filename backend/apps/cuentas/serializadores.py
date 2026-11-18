from rest_framework import serializers

from apps.core.serializadores import SerializadorEstricto


class SerializadorLogin(SerializadorEstricto):
    """Datos del inicio de sesión. Solo comprueba la forma, no las credenciales."""

    correo = serializers.EmailField(max_length=254)
    # Sin recortar espacios: la contraseña se compara tal como se escribió.
    # El largo máximo evita gastar tiempo de hash en entradas enormes.
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class SerializadorCambioPassword(SerializadorEstricto):
    """Datos del cambio de contraseña. La política se aplica en el servicio."""

    password_actual = serializers.CharField(max_length=128, trim_whitespace=False)
    password_nueva = serializers.CharField(max_length=128, trim_whitespace=False)


class SerializadorCodigoMfa(SerializadorEstricto):
    """Código del segundo factor: 6 dígitos del TOTP o un código de recuperación."""

    # Se ignoran los espacios que la persona copie alrededor del código.
    codigo = serializers.CharField(max_length=20, trim_whitespace=True)
