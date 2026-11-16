#!/usr/bin/env python
"""Punto de entrada para los comandos de administración de NotIA."""

import os
import sys


def main() -> None:
    # En la terminal local se trabaja con la configuración de desarrollo.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as error:
        raise ImportError(
            "No se pudo importar Django. Activa el entorno virtual e instala "
            "las dependencias con: pip install -r requirements/dev.txt"
        ) from error
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
