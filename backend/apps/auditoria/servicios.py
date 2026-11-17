"""Servicio para escribir en la bitácora de auditoría (RS-16).

Es la única puerta de entrada a la bitácora: el resto del sistema llama a
``registrar`` y nunca crea un ``RegistroAuditoria`` por su cuenta. Así las
reglas de qué se puede guardar están en un solo lugar.

Lo que nunca entra a la bitácora: contraseñas (ni las fallidas), tokens,
códigos de 2FA, alternativas elegidas ni texto de preguntas. Quien llama no
debe enviarlos; si aun así llegan en ``detalle``, se reemplazan por ``***``.
"""

import ipaddress
import re
from typing import Any

from django.db import models
from django.http import HttpRequest

from apps.core.registros import MASCARA, PATRON_NOMBRE_SENSIBLE, enmascarar_texto

from .models import LARGO_USER_AGENT, Accion, RegistroAuditoria

# Además de los nombres que ya enmascara el filtro de registros (contraseñas,
# tokens, códigos, alternativas y respuestas), en la bitácora tampoco se
# guarda el texto de una pregunta ni de una alternativa.
_PATRON_TEXTO_DE_PRUEBA = re.compile(r"texto|enunciado", re.IGNORECASE)

_VALORES_SIMPLES = (str, int, float, bool, type(None))
_LARGO_OBJETO_TIPO = RegistroAuditoria._meta.get_field("objeto_tipo").max_length
_LARGO_OBJETO_ID = RegistroAuditoria._meta.get_field("objeto_id").max_length
_LARGO_ROL = RegistroAuditoria._meta.get_field("rol_actor").max_length


def _es_nombre_prohibido(nombre: str) -> bool:
    return bool(PATRON_NOMBRE_SENSIBLE.search(nombre) or _PATRON_TEXTO_DE_PRUEBA.search(nombre))


def _limpiar(nombre: str, valor: Any) -> Any:
    """Deja un valor listo para guardarse como JSON, sin datos prohibidos."""
    if _es_nombre_prohibido(nombre):
        return MASCARA
    if isinstance(valor, dict):
        return {str(clave): _limpiar(str(clave), interno) for clave, interno in valor.items()}
    if isinstance(valor, list | tuple | set | frozenset):
        return [_limpiar(nombre, interno) for interno in valor]
    if isinstance(valor, str):
        return enmascarar_texto(valor)
    if isinstance(valor, _VALORES_SIMPLES):
        return valor
    # UUID, fechas, decimales y similares se guardan como texto.
    return enmascarar_texto(str(valor))


def limpiar_detalle(detalle: dict | None) -> dict:
    """Devuelve una copia del detalle sin datos que la bitácora no puede guardar."""
    if detalle is None:
        return {}
    if not isinstance(detalle, dict):
        raise TypeError("El detalle de un registro de auditoría debe ser un diccionario.")
    return {str(clave): _limpiar(str(clave), valor) for clave, valor in detalle.items()}


def _ip_valida(texto: str | None) -> str | None:
    """Devuelve la dirección normalizada, o ``None`` si no es una dirección IP."""
    try:
        return str(ipaddress.ip_address((texto or "").strip()))
    except ValueError:
        return None


def origen_de(peticion: HttpRequest | None) -> tuple[str | None, str]:
    """Devuelve la IP y el navegador (recortado) de una petición.

    La IP es la de la conexión que recibe Django (``REMOTE_ADDR``). No se lee
    ``X-Forwarded-For``, porque cualquier cliente puede escribir esa cabecera.
    """
    if peticion is None:
        return None, ""
    ip = _ip_valida(peticion.META.get("REMOTE_ADDR"))
    navegador = str(peticion.META.get("HTTP_USER_AGENT", ""))[:LARGO_USER_AGENT]
    return ip, navegador


def registrar(
    accion: Accion,
    *,
    actor=None,
    peticion: HttpRequest | None = None,
    objeto: models.Model | None = None,
    detalle: dict | None = None,
) -> RegistroAuditoria:
    """Agrega un registro a la bitácora y lo devuelve.

    - ``accion``: uno de los valores de ``Accion``.
    - ``actor``: el usuario que hizo la acción; ``None`` si no se sabe quién
      fue (por ejemplo, un inicio de sesión fallido con un correo inexistente).
    - ``peticion``: la petición HTTP, de la que se toman la IP y el navegador.
    - ``objeto``: el registro afectado; se anotan su tipo y su identificador.
    - ``detalle``: datos adicionales, sin información sensible.

    Si el registro no se puede guardar, la excepción se propaga: una acción
    que debe quedar en la bitácora no continúa sin dejar rastro.
    """
    accion = Accion(accion)
    if actor is not None and not getattr(actor, "pk", None):
        raise ValueError("El actor de un registro de auditoría debe ser un usuario guardado.")

    ip, navegador = origen_de(peticion)
    objeto_tipo, objeto_id = "", ""
    if objeto is not None:
        objeto_tipo = objeto._meta.label[:_LARGO_OBJETO_TIPO]
        objeto_id = str(objeto.pk)[:_LARGO_OBJETO_ID]

    return RegistroAuditoria.objects.create(
        accion=accion,
        actor=actor,
        # El rol se agrega al modelo Usuario en el PR 1.2; hasta entonces queda vacío.
        rol_actor=str(getattr(actor, "rol", "") or "")[:_LARGO_ROL],
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        ip=ip,
        user_agent=navegador,
        detalle=limpiar_detalle(detalle),
    )
