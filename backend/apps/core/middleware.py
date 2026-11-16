"""Cabeceras de seguridad para todas las respuestas (RS-13).

La Content-Security-Policy no admite ``'unsafe-inline'`` ni ``'unsafe-eval'``.
Astro inserta algunos scripts y estilos en línea para hidratar las islas; se
permiten uno por uno con su hash SHA-256, que ``frontend/scripts/hash-csp.mjs``
calcula después de cada build y deja en ``csp-hashes.json``.
"""

import json
import logging
import re
from pathlib import Path

from django.conf import settings

registro = logging.getLogger(__name__)

# Un hash SHA-256 en base64 tiene siempre 44 caracteres. Todo lo que no calce
# se descarta, para que un archivo alterado no pueda inyectar directivas.
PATRON_HASH = re.compile(r"sha256-[A-Za-z0-9+/]{43}=")

TIPOS_CON_HASH = ("script", "style")

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"


def leer_hashes(ruta: Path) -> dict[str, tuple[str, ...]]:
    """Lee ``csp-hashes.json`` y devuelve solo los hashes bien formados.

    Si el archivo no existe o está dañado, la política queda sin hashes: los
    scripts en línea se bloquean, que es el comportamiento seguro.
    """
    vacio: dict[str, tuple[str, ...]] = {tipo: () for tipo in TIPOS_CON_HASH}
    if not ruta.is_file():
        registro.info("No hay archivo de hashes de CSP; la política no permite código en línea.")
        return vacio
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        registro.warning("El archivo de hashes de CSP no se pudo leer; se ignora.")
        return vacio
    if not isinstance(contenido, dict):
        registro.warning("El archivo de hashes de CSP no tiene el formato esperado; se ignora.")
        return vacio

    hashes = {}
    for tipo in TIPOS_CON_HASH:
        candidatos = contenido.get(tipo, [])
        if not isinstance(candidatos, list):
            candidatos = []
        validos = [
            valor for valor in candidatos if isinstance(valor, str) and PATRON_HASH.fullmatch(valor)
        ]
        if len(validos) != len(candidatos):
            registro.warning("Se descartaron hashes de CSP mal formados (%s).", tipo)
        hashes[tipo] = tuple(sorted(set(validos)))
    return hashes


def construir_csp(hashes: dict[str, tuple[str, ...]]) -> str:
    """Arma la política completa. Las fuentes son fijas; solo varían los hashes."""

    def propias_y_hashes(tipo: str) -> str:
        return " ".join(["'self'", *(f"'{valor}'" for valor in hashes.get(tipo, ()))])

    directivas = (
        ("default-src", "'self'"),
        ("script-src", propias_y_hashes("script")),
        ("style-src", propias_y_hashes("style")),
        ("img-src", "'self' blob: data:"),
        ("media-src", "'self' blob:"),
        ("connect-src", "'self'"),
        ("font-src", "'self'"),
        ("object-src", "'none'"),
        ("base-uri", "'none'"),
        ("frame-ancestors", "'none'"),
        ("form-action", "'self'"),
    )
    return "; ".join(f"{nombre} {fuentes}" for nombre, fuentes in directivas)


def construir_hsts() -> str:
    """Valor de Strict-Transport-Security, o vacío si el entorno no lo usa."""
    segundos = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
    if segundos <= 0:
        return ""
    partes = [f"max-age={segundos}"]
    if getattr(settings, "SECURE_HSTS_INCLUDE_SUBDOMAINS", False):
        partes.append("includeSubDomains")
    if getattr(settings, "SECURE_HSTS_PRELOAD", False):
        partes.append("preload")
    return "; ".join(partes)


class CabecerasSeguridadMiddleware:
    """Agrega las cabeceras de seguridad a todas las respuestas.

    Va primero en ``MIDDLEWARE`` para cubrir también los errores y las
    redirecciones que generan los demás middlewares. La política se calcula
    una vez, al arrancar.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = construir_csp(leer_hashes(Path(settings.CSP_ARCHIVO_HASHES)))
        self.hsts = construir_hsts()

    def __call__(self, request):
        respuesta = self.get_response(request)

        respuesta["Content-Security-Policy"] = self.csp
        respuesta["X-Content-Type-Options"] = "nosniff"
        respuesta["Referrer-Policy"] = "same-origin"
        respuesta["Permissions-Policy"] = PERMISSIONS_POLICY
        respuesta["Cross-Origin-Opener-Policy"] = "same-origin"
        respuesta["Cross-Origin-Resource-Policy"] = "same-origin"

        # HSTS solo tiene sentido sobre HTTPS, es decir, en producción.
        if self.hsts and request.is_secure():
            respuesta["Strict-Transport-Security"] = self.hsts

        # Nada de lo que responde la API se guarda en cachés del navegador ni intermedios.
        if request.path.startswith("/api/"):
            respuesta["Cache-Control"] = "no-store"

        return respuesta
