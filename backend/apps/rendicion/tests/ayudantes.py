"""Ayudantes de las pruebas de rendición: preparar una prueba y recorrerla por la API."""

from apps.evaluaciones.models import Modalidad
from apps.evaluaciones.tests.fabricas import (
    asignar,
    crear_alumno,
    crear_evaluacion,
    sesion_de,
)

VOZ = "es-CL-CatalinaNeural"
OTRA_VOZ = "es-CL-LorenzoNeural"


def preparar(
    *, preguntas: int = 3, tiempo: int = 60, modalidad: str = Modalidad.NOTIA, **campos
):
    """Evaluación publicada y abierta, un alumno asignado y su navegador.

    Por omisión las preguntas no se barajan, para saber cuál viene primero.
    """
    campos.setdefault("aleatorizar_preguntas", False)
    evaluacion = crear_evaluacion(preguntas=preguntas, publicada=True, **campos)
    evaluacion.preguntas.update(tiempo_segundos=tiempo)
    alumno = crear_alumno()
    asignar(evaluacion, alumno, modalidad)
    return evaluacion, alumno, sesion_de(alumno)


def iniciar(navegador, evaluacion, voz: str | None = VOZ):
    datos = {"voz": voz} if voz is not None else {}
    return navegador.enviar(f"/api/alumno/evaluaciones/{evaluacion.id}/iniciar", datos)


def iniciado(navegador, evaluacion, voz: str | None = VOZ) -> str:
    respuesta = iniciar(navegador, evaluacion, voz)
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()["intento"]


def actual(navegador, intento_id):
    return navegador.get(f"/api/alumno/intentos/{intento_id}/actual")


def responder(navegador, intento_id, ref, alternativa_id):
    return navegador.enviar(
        f"/api/alumno/intentos/{intento_id}/responder",
        {"ref": str(ref), "alternativa_id": str(alternativa_id)},
    )


def pasar(navegador, intento_id, ref):
    return navegador.enviar(f"/api/alumno/intentos/{intento_id}/pasar", {"ref": str(ref)})


def cambiar_voz(navegador, intento_id, voz):
    return navegador.patch(
        f"/api/alumno/intentos/{intento_id}/voz",
        {"voz": voz},
        format="json",
        HTTP_X_CSRFTOKEN=navegador.cookies["csrftoken"].value,
    )


def primera_alternativa(cuerpo) -> str:
    return cuerpo["pregunta"]["alternativas"][0]["id"]


def responder_primera(navegador, intento_id, cuerpo):
    """Responde la pregunta de ``cuerpo`` con su primera alternativa en pantalla."""
    return responder(navegador, intento_id, cuerpo["pregunta"]["ref"], primera_alternativa(cuerpo))
