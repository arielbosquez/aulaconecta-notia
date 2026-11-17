"""Registros (logging) en JSON y sin datos sensibles.

Cada registro sale por la salida estándar como una línea JSON, que es lo que
recoge Azure App Service. Antes de escribirse pasa por un filtro que
enmascara contraseñas, tokens, cookies, códigos de 2FA y respuestas de
alumnos, tanto en el mensaje como en los datos adicionales y en las trazas.

El filtro es una segunda barrera: la primera regla es no registrar nunca
esos datos.
"""

import json
import logging
import re
from datetime import UTC, datetime

MASCARA = "***"

# Fragmentos que delatan un dato sensible en el nombre de un campo.
_NOMBRES = (
    r"password|passwd|contrase[nñ]a|clave|secret|secreto|token|jwt|cookie|authorization|"
    r"csrf|sessionid|codigo|otp|totp|mfa|llave|signing|api[_-]?key|alternativa|respuesta"
)
PATRON_NOMBRE_SENSIBLE = re.compile(_NOMBRES, re.IGNORECASE)

# nombre=valor, nombre: valor o "nombre": "valor" dentro de un texto.
PATRON_PAR = re.compile(
    rf"""(?P<nombre>[\w.-]*(?:{_NOMBRES})[\w.-]*)
         (?P<separador>["']?\s*[=:]\s*)
         (?P<valor>"[^"]*"|'[^']*'|[^\s,;&)}}\]]+)""",
    re.IGNORECASE | re.VERBOSE,
)
# Tokens que se reconocen por su forma, aunque nadie los nombre.
PATRON_JWT = re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*")
PATRON_PORTADOR = re.compile(r"\b(Bearer|Basic)\s+[\w.~+/=-]+", re.IGNORECASE)

# Atributos propios de logging.LogRecord: no son datos adicionales.
_ATRIBUTOS_BASE = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

# Lo único que se copia al registro tal cual; el resto se omite.
_TIPOS_REGISTRABLES = (str, int, float, bool, type(None), dict, list)


def enmascarar_texto(texto: str) -> str:
    """Reemplaza por ``***`` los valores sensibles que aparezcan en un texto."""
    texto = PATRON_JWT.sub(MASCARA, texto)
    texto = PATRON_PORTADOR.sub(lambda hallazgo: f"{hallazgo.group(1)} {MASCARA}", texto)
    return PATRON_PAR.sub(
        lambda hallazgo: f"{hallazgo.group('nombre')}{hallazgo.group('separador')}{MASCARA}",
        texto,
    )


def enmascarar_dato(nombre: str, valor):
    """Enmascara un dato adicional según su nombre y, si es texto, su contenido."""
    if PATRON_NOMBRE_SENSIBLE.search(nombre):
        return MASCARA
    if isinstance(valor, str):
        return enmascarar_texto(valor)
    if isinstance(valor, dict):
        return {
            str(clave): enmascarar_dato(str(clave), interno) for clave, interno in valor.items()
        }
    if isinstance(valor, list | tuple):
        return [enmascarar_dato(nombre, interno) for interno in valor]
    return valor


class FiltroDatosSensibles(logging.Filter):
    """Enmascara los datos sensibles de cada registro antes de escribirlo."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            mensaje = record.getMessage()
        except (TypeError, ValueError):
            mensaje = str(record.msg)
        # El mensaje queda ya armado, para que los argumentos también pasen por la máscara.
        record.msg = enmascarar_texto(mensaje)
        record.args = None

        for nombre, valor in list(vars(record).items()):
            if nombre not in _ATRIBUTOS_BASE:
                setattr(record, nombre, enmascarar_dato(nombre, valor))
        return True


class FormateadorJson(logging.Formatter):
    """Escribe cada registro como un objeto JSON en una sola línea."""

    def format(self, record: logging.LogRecord) -> str:
        salida = {
            "momento": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "nivel": record.levelname,
            "origen": record.name,
            "mensaje": record.getMessage(),
        }

        for nombre, valor in vars(record).items():
            if nombre in _ATRIBUTOS_BASE or nombre.startswith("_"):
                continue
            if nombre == "request":
                # De la petición solo se anotan el método y la ruta: nunca
                # cabeceras, cookies, parámetros ni cuerpo.
                metodo, ruta = getattr(valor, "method", None), getattr(valor, "path", None)
                if isinstance(metodo, str) and isinstance(ruta, str):
                    salida["metodo"], salida["ruta"] = metodo, ruta
            elif isinstance(valor, _TIPOS_REGISTRABLES):
                salida[nombre] = valor
            # Cualquier otro objeto se omite: no se sabe qué contiene.

        if record.exc_info:
            salida["excepcion"] = enmascarar_texto(self.formatException(record.exc_info))

        return json.dumps(salida, ensure_ascii=False, default=lambda _: MASCARA)
