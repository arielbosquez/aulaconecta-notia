"""Límite de peticiones de login por IP (sección 12.7, RS-02).

Usa el throttling de Django REST Framework con la caché en base de datos,
así el conteo es común a todos los workers. La IP la decide
``apps.core.red.ip_del_cliente``, la misma función que usa la bitácora: un
``X-Forwarded-For`` escrito por el navegador no cambia la IP contada, así
que falsificarlo no sirve para esquivar el límite.

Limitación conocida: DRF lee y escribe el historial de la IP en dos pasos,
sin bloqueo. Una ráfaga de peticiones exactamente simultáneas puede pasar
alguna de más antes de que el límite se note. El bloqueo por cuenta, que sí
es atómico, sigue acotando los intentos contra cada usuario.
"""

import ipaddress

from rest_framework.throttling import SimpleRateThrottle

from apps.core.red import ip_del_cliente

# Un proveedor suele entregar a cada cliente un bloque IPv6 /64 completo:
# contar cada dirección por separado le daría millones de "IP" distintas a
# una sola persona. Para IPv6 se cuenta el bloque /64.
PREFIJO_IPV6 = 64

SIN_IP = "desconocida"


def identificador_de_red(ip: str | None) -> str:
    """Lo que se cuenta para el límite: la IPv4, o el bloque /64 de una IPv6."""
    if not ip:
        # Sin IP conocida, todas esas peticiones comparten un solo contador.
        return SIN_IP
    direccion = ipaddress.ip_address(ip)
    if direccion.version == 6 and direccion.ipv4_mapped:
        # Un servidor que escucha en IPv6 ve a los clientes IPv4 como
        # ::ffff:a.b.c.d. Se cuentan por su IPv4: si no, todos caerían en el
        # mismo bloque /64 y compartirían un solo contador.
        direccion = direccion.ipv4_mapped
    if direccion.version == 6:
        return str(ipaddress.ip_network(f"{direccion}/{PREFIJO_IPV6}", strict=False))
    return str(direccion)


class LimiteDeLoginPorIp(SimpleRateThrottle):
    """10 peticiones de login por minuto por IP (``DEFAULT_THROTTLE_RATES["login"]``).

    Cuenta todas las peticiones al endpoint, correctas o no: así tampoco se
    puede probar una misma contraseña contra muchos correos distintos.
    """

    scope = "login"

    def get_cache_key(self, request, view):
        ident = identificador_de_red(ip_del_cliente(request))
        return self.cache_format % {"scope": self.scope, "ident": ident}
