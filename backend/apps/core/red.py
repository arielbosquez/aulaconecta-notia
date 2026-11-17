"""Dirección IP del cliente, sin confiar en lo que mande el navegador.

Es la única función del proyecto que decide cuál es la IP de quien hace una
petición. La usan la bitácora de auditoría y los límites de intentos por IP.

El problema: la cabecera ``X-Forwarded-For`` la puede escribir cualquiera. Un
atacante que la falsifica podría esquivar el límite de intentos (una IP
distinta en cada petición) o dejar en la bitácora la IP de otra persona.

La regla:

- En desarrollo no hay proxy (``PROXIES_DE_CONFIANZA = 0``): la IP es la de la
  conexión, ``REMOTE_ADDR``, y la cabecera se ignora por completo.
- En producción, Django está detrás del proxy de Azure App Service. Cada proxy
  **agrega al final** de ``X-Forwarded-For`` la dirección de quien se conectó
  a él. Con ``PROXIES_DE_CONFIANZA = 1`` la IP del cliente es entonces la
  última entrada de la lista, la única que escribió Azure. Todo lo que esté
  antes pudo escribirlo el navegador y se descarta.
- Con más proxies propios delante (por ejemplo, Front Door y App Service), se
  cuenta desde el final tantas entradas como proxies de confianza haya.
"""

import ipaddress

from django.conf import settings

CABECERA_REENVIO = "HTTP_X_FORWARDED_FOR"


def normalizar_ip(texto: str | None) -> str | None:
    """Devuelve la dirección en su forma estándar, o ``None`` si no es una IP.

    Acepta las formas con puerto que usan los proxies: ``203.0.113.7:51234``
    y ``[2001:db8::1]:51234``.
    """
    candidato = (texto or "").strip()
    if not candidato:
        return None
    if candidato.startswith("["):
        # IPv6 entre corchetes, con o sin puerto.
        candidato = candidato[1:].partition("]")[0]
    elif candidato.count(":") == 1:
        # IPv4 con puerto. Una IPv6 sin corchetes tiene más de un ":".
        candidato = candidato.partition(":")[0]
    try:
        return str(ipaddress.ip_address(candidato))
    except ValueError:
        return None


def ip_del_cliente(peticion) -> str | None:
    """Devuelve la IP del cliente de una petición, o ``None`` si no se puede saber."""
    meta = getattr(peticion, "META", {})
    conexion = normalizar_ip(meta.get("REMOTE_ADDR"))

    proxies = settings.PROXIES_DE_CONFIANZA
    if proxies <= 0:
        return conexion

    entradas = [parte.strip() for parte in str(meta.get(CABECERA_REENVIO, "")).split(",")]
    entradas = [parte for parte in entradas if parte]
    if len(entradas) < proxies:
        # La petición no pasó por todos los proxies esperados (por ejemplo,
        # una revisión de estado interna): lo único cierto es la conexión.
        return conexion

    # Contando desde el final, la entrada que agregó el proxy más externo de
    # los nuestros. Las anteriores vienen de fuera y no se leen.
    return normalizar_ip(entradas[-proxies]) or conexion
