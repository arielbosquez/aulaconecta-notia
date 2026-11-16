"""Lectura de la configuración desde variables de entorno.

Toda la configuración sensible de NotIA llega por variables de entorno. Este
módulo es el único lugar que las lee, para que la regla sea la misma en todos
los settings:

- En producción, una variable obligatoria que falta o viene vacía detiene el
  arranque con un error claro. Nunca se sigue con un valor por omisión.
- Fuera de producción (desarrollo y pruebas) se acepta el valor por omisión.

Los mensajes de error nombran la variable, pero jamás muestran su valor.
"""

import os
from collections.abc import Iterable
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Únicas configuraciones que se consideran locales. Cualquier otra (incluida
# una desconocida o mal escrita) se trata como producción, que es lo estricto.
CONFIGURACIONES_LOCALES = frozenset({"config.settings.dev", "config.settings.test"})


def es_produccion() -> bool:
    """Indica si el proceso corre con una configuración que no es local."""
    return os.environ.get("DJANGO_SETTINGS_MODULE", "") not in CONFIGURACIONES_LOCALES


def cargar_archivo_env(ruta: Path) -> None:
    """Carga un archivo ``.env`` local sin pisar lo que ya trae el entorno.

    Solo se usa en desarrollo y pruebas. Acepta líneas ``NOMBRE=valor``,
    líneas vacías y comentarios que empiezan con ``#``. No interpreta
    comillas anidadas ni sustituye variables: el archivo es una lista simple.
    """
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        nombre, _, valor = linea.partition("=")
        nombre = nombre.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if nombre and nombre not in os.environ:
            os.environ[nombre] = valor


def leer(nombre: str, *, defecto: str = "", obligatoria: bool = False) -> str:
    """Devuelve el valor de una variable de entorno.

    Si ``obligatoria`` es verdadero y la variable falta en producción, lanza
    ``ImproperlyConfigured``. El ``defecto`` solo se usa fuera de producción
    o cuando la variable es opcional.
    """
    valor = os.environ.get(nombre, "").strip()
    if valor:
        return valor
    if obligatoria and es_produccion():
        raise ImproperlyConfigured(
            f"Falta la variable de entorno obligatoria {nombre}. "
            "En producción no se usan valores por omisión."
        )
    return defecto


def leer_lista(nombre: str, *, defecto: Iterable[str] = (), obligatoria: bool = False) -> list[str]:
    """Lee una variable con valores separados por coma y descarta los vacíos."""
    valor = leer(nombre, obligatoria=obligatoria)
    if not valor:
        return list(defecto)
    return [parte.strip() for parte in valor.split(",") if parte.strip()]


def leer_opcion(
    nombre: str, *, opciones: Iterable[str], defecto: str, obligatoria: bool = False
) -> str:
    """Lee una variable que solo admite los valores de una lista cerrada."""
    permitidas = tuple(opciones)
    valor = leer(nombre, defecto=defecto, obligatoria=obligatoria).lower()
    if valor not in permitidas:
        raise ImproperlyConfigured(
            f"La variable de entorno {nombre} debe ser una de: {', '.join(permitidas)}."
        )
    return valor
