"""Base de los serializadores de entrada de la API (RS-10)."""

from rest_framework import serializers


class SerializadorEstricto(serializers.Serializer):
    """Serializador que rechaza los campos que no conoce.

    Por omisión, DRF ignora en silencio los campos de más. Aquí una petición
    con un campo desconocido se rechaza completa: así un cliente no puede
    colar datos que alguna vista termine usando sin validarlos.
    """

    def to_internal_value(self, data):
        if isinstance(data, dict):
            desconocidos = sorted(set(data) - set(self.fields))
            if desconocidos:
                raise serializers.ValidationError(
                    {str(campo)[:50]: ["Este campo no está permitido."] for campo in desconocidos}
                )
        return super().to_internal_value(data)
