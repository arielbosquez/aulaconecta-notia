"""Contenedor privado de Azure Blob Storage, con identidad administrada.

Se importa solo desde la configuración de producción: así el resto de los
entornos no necesita las librerías de Azure cargadas.
"""

from storages.backends.azure_storage import AzureStorage

from .almacenamiento import SinUrlPublica


class AlmacenamientoAzurePrivado(SinUrlPublica, AzureStorage):
    """Blob Storage sin cadenas de conexión ni llaves.

    App Service entra con su identidad administrada (``DefaultAzureCredential``),
    y el contenedor no permite acceso anónimo. Nunca se generan URLs firmadas.
    """

    def __init__(self, **opciones):
        if "token_credential" not in opciones:
            from azure.identity import DefaultAzureCredential

            opciones["token_credential"] = DefaultAzureCredential()
        # Un archivo con el mismo nombre nunca se pisa: los nombres son aleatorios.
        opciones.setdefault("overwrite_files", False)
        super().__init__(**opciones)
