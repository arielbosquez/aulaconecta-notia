from rest_framework import serializers

from apps.core.serializadores import SerializadorEstricto


class SerializadorLogin(SerializadorEstricto):
    """Datos del inicio de sesión. Solo comprueba la forma, no las credenciales."""

    correo = serializers.EmailField(max_length=254)
    # Sin recortar espacios: la contraseña se compara tal como se escribió.
    # El largo máximo evita gastar tiempo de hash en entradas enormes.
    password = serializers.CharField(max_length=128, trim_whitespace=False)
