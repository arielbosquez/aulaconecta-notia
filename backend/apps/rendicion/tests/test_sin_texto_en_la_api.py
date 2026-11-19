"""Ninguna respuesta de la API entrega la pregunta ni la respuesta correcta (RS-08).

Un alumno rinde una evaluación completa en modalidad NotIA, como lo haría
desde el navegador: inicia sesión, revisa sus pruebas, escucha las muestras
de voz, avisa al docente, empieza, escucha cada pregunta, registra eventos
de integridad, pasa una, cambia la voz, se equivoca
de petición, responde todo, vuelve en la ronda 2, termina, ve su nota
publicada y cierra sesión. Cada respuesta de la API, sea JSON o audio, y sus
cabeceras quedan guardadas, y después se buscan en ellas:

- el texto de cada pregunta (tal cual, escapado como JSON y en trozos),
- la cadena ``es_correcta`` y cualquier rastro de "correct",
- el puntaje y el identificador interno de cada pregunta.
"""

import json

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core.almacenamiento import almacenamiento_privado
from apps.cuentas.tests.conftest import CLAVE, Navegador
from apps.evaluaciones.models import Modalidad
from apps.evaluaciones.tests.fabricas import (
    asignar,
    crear_alumno,
    crear_evaluacion,
    crear_pregunta,
)
from apps.rendicion.models import Intento
from apps.resultados.models import EstadoResultado, Resultado
from apps.voz.proveedores import ProveedorPrueba, voces_disponibles
from apps.voz.servicios import audio_de_pregunta

from .ayudantes import OTRA_VOZ, VOZ

pytestmark = pytest.mark.django_db

# Textos con tildes, signos y comillas: así también se busca su forma escapada.
TEXTOS = [
    "¿Cuál es la capital de Chile? Elige la ciudad «correcta» entre las opciones.",
    "Si un tren sale a las 8:15 y llega a las 9:40, ¿cuánto demoró el viaje?",
    'Lee con atención: "fotosíntesis" es el proceso por el que las plantas…',
    "¿Qué número sigue en la serie 2, 4, 8, 16? Piensa antes de responder & elige.",
    "Indica cuál de estas palabras es aguda <según la regla> de acentuación.",
]
# Ningún puntaje se parece a otro número de las respuestas.
PUNTAJES = [17, 23, 29, 31, 37]


class NavegadorQueAnota(Navegador):
    """Navegador que guarda cada respuesta de la API que recibe."""

    def __init__(self):
        super().__init__()
        self.anotadas: list[tuple[str, int, bytes]] = []

    def request(self, **peticion):
        respuesta = super().request(**peticion)
        cabeceras = "\n".join(f"{k}: {v}" for k, v in respuesta.items()).encode()
        self.anotadas.append(
            (peticion.get("PATH_INFO", ""), respuesta.status_code, respuesta.content + cabeceras)
        )
        return respuesta

    def parchar(self, ruta, datos):
        return self.patch(
            ruta, datos, format="json", HTTP_X_CSRFTOKEN=self.cookies["csrftoken"].value
        )


def _formas_prohibidas(evaluacion) -> dict[str, bytes]:
    """Todo lo que no puede aparecer en ninguna respuesta, con su motivo."""
    prohibidas = {
        "es_correcta": b"es_correcta",
        "correct": b"correct",
        "puntaje": b'"puntaje"',
    }
    for pregunta in evaluacion.preguntas.all():
        texto = pregunta.texto
        n = pregunta.orden
        prohibidas[f"texto {n}"] = texto.encode()
        # Como lo escribiría un JSON con ensure_ascii (¿…) o sin él.
        prohibidas[f"texto {n} (JSON ascii)"] = json.dumps(texto)[1:-1].encode()
        prohibidas[f"texto {n} (JSON utf-8)"] = json.dumps(texto, ensure_ascii=False)[1:-1].encode()
        # Un trozo del medio, por si se enviara recortado.
        mitad = len(texto) // 2
        prohibidas[f"trozo del texto {n}"] = texto[mitad - 10 : mitad + 10].encode()
        prohibidas[f"id de la pregunta {n}"] = str(pregunta.id).encode()
        prohibidas[f"id hex de la pregunta {n}"] = pregunta.id.hex.encode()
    return prohibidas


def _preparar_evaluacion():
    evaluacion = crear_evaluacion(publicada=True, titulo="Prueba de cultura general")
    for orden, (texto, puntaje) in enumerate(zip(TEXTOS, PUNTAJES, strict=True), start=1):
        crear_pregunta(evaluacion, orden=orden, texto=texto, puntaje=puntaje, tiempo_segundos=60)
    # La tercera pregunta tiene una imagen (ya reconvertida, como dejará la Fase 3).
    imagen = ContentFile(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    ruta = almacenamiento_privado().save("imagenes/prueba.webp", imagen)
    evaluacion.preguntas.filter(orden=3).update(imagen=ruta)
    # Los audios se generan al publicar, para cada voz.
    for pregunta in evaluacion.preguntas.all():
        for voz in voces_disponibles():
            audio_de_pregunta(pregunta, voz, ProveedorPrueba())
    return evaluacion


def _rendir_completa(navegador, evaluacion) -> str:
    """Recorre la prueba completa por la API. Devuelve el id del intento."""
    assert navegador.get("/api/auth/yo").status_code == 200
    assert navegador.get("/api/alumno/evaluaciones").status_code == 200
    for voz in navegador.get("/api/alumno/voces").json()["voces"]:
        assert navegador.get(voz["muestra_url"]).status_code == 200
    # Los dos avisos al docente de la pantalla de preparación (CU-08).
    for tipo in ("NINGUNA_VOZ_SIRVE", "NECESITO_OTRA_MODALIDAD"):
        aviso = {"evaluacion": str(evaluacion.id), "tipo": tipo}
        assert navegador.enviar("/api/alumno/solicitudes", aviso).status_code == 201

    iniciar = navegador.enviar(f"/api/alumno/evaluaciones/{evaluacion.id}/iniciar", {"voz": VOZ})
    assert iniciar.status_code == 201
    intento_id = iniciar.json()["intento"]
    base = f"/api/alumno/intentos/{intento_id}"

    cuerpo = navegador.get(f"{base}/actual").json()
    vueltas, paso = 0, 0
    while cuerpo["pregunta"] is not None:
        vueltas += 1
        assert vueltas < 20, "La prueba no terminó"
        pregunta = cuerpo["pregunta"]
        ref = pregunta["ref"]

        assert navegador.get(pregunta["audio_url"]).status_code == 200
        if pregunta["imagen_url"]:
            assert navegador.get(pregunta["imagen_url"]).status_code == 200
        assert navegador.enviar(f"/api/alumno/respuestas/{ref}/repeticion").status_code == 204
        eventos = {
            "eventos": [{"tipo": "PERDIO_FOCO"}, {"tipo": "RECUPERO_FOCO", "duracion_ms": 900}]
        }
        assert navegador.enviar(f"{base}/eventos", eventos).status_code == 201
        assert navegador.get(f"{base}/actual").status_code == 200

        if paso == 0:
            # La primera se pasa, para que vuelva en la ronda 2.
            paso += 1
            cuerpo = navegador.enviar(f"{base}/pasar", {"ref": ref}).json()
            continue
        if paso == 1:
            # En la segunda cambia la voz y vuelve a pedir el audio.
            paso += 1
            assert navegador.parchar(f"{base}/voz", {"voz": OTRA_VOZ}).status_code == 200
            assert navegador.get(pregunta["audio_url"]).status_code == 200
            # Una alternativa inventada y una de otra pregunta: errores que también se revisan.
            invalida = {"ref": ref, "alternativa_id": "00000000-0000-0000-0000-000000000000"}
            assert navegador.enviar(f"{base}/responder", invalida).status_code == 400
            assert navegador.enviar(f"{base}/responder", {"ref": ref}).status_code == 400

        elegida = pregunta["alternativas"][vueltas % len(pregunta["alternativas"])]["id"]
        respuesta = navegador.enviar(f"{base}/responder", {"ref": ref, "alternativa_id": elegida})
        assert respuesta.status_code == 200
        # Enviar dos veces la misma respuesta: 409, y el error también se revisa.
        repetida = navegador.enviar(f"{base}/responder", {"ref": ref, "alternativa_id": elegida})
        assert repetida.status_code == 409
        cuerpo = respuesta.json()

    assert cuerpo["estado"] == "FINALIZADO"
    assert navegador.get(f"{base}/actual").status_code == 200
    assert navegador.get("/api/alumno/evaluaciones").status_code == 200
    return intento_id


def test_un_recorrido_completo_en_notia_no_entrega_el_texto_ni_la_respuesta_correcta():
    evaluacion = _preparar_evaluacion()
    alumno = crear_alumno(correo="alumno.recorrido.demo@aulaconecta.cl")
    asignar(evaluacion, alumno, Modalidad.NOTIA)

    navegador = NavegadorQueAnota()
    assert navegador.login(alumno.correo, CLAVE).status_code == 200
    intento_id = _rendir_completa(navegador, evaluacion)

    # La nota, una vez publicada, tampoco trae nada de las preguntas.
    assert navegador.get("/api/alumno/resultados").status_code == 200
    Resultado.objects.filter(intento_id=intento_id).update(
        estado=EstadoResultado.PUBLICADO, publicado_en=timezone.now()
    )
    publicados = navegador.get("/api/alumno/resultados").json()["resultados"]
    assert len(publicados) == 1
    assert navegador.enviar("/api/auth/logout").status_code in (200, 204)

    # Se recorrió de verdad: todas respondidas, una de ellas en la ronda 2.
    intento = Intento.objects.get(pk=intento_id)
    assert intento.ronda == 2
    assert intento.respuestas.filter(alternativa__isnull=False).count() == len(TEXTOS)

    anotadas = navegador.anotadas
    assert len(anotadas) > 40
    rutas = {ruta.split("/")[-1] for ruta, _, _ in anotadas}
    esperadas = {"audio", "imagen", "actual", "responder", "pasar", "voz", "repeticion"}
    assert esperadas | {"eventos", "solicitudes", "muestra", "resultados"} <= rutas
    assert all(estado < 500 for _, estado, _ in anotadas)

    hallazgos = [
        f"{motivo} en {ruta} ({estado})"
        for ruta, estado, contenido in anotadas
        for motivo, forma in _formas_prohibidas(evaluacion).items()
        if forma in contenido
    ]
    assert hallazgos == []


def test_en_modalidad_normal_solo_llega_el_texto_de_la_pregunta_en_curso():
    evaluacion = _preparar_evaluacion()
    alumno = crear_alumno(correo="alumna.normal.demo@aulaconecta.cl")
    asignar(evaluacion, alumno, Modalidad.NORMAL)
    navegador = NavegadorQueAnota()
    navegador.login(alumno.correo, CLAVE)
    intento_id = navegador.enviar(f"/api/alumno/evaluaciones/{evaluacion.id}/iniciar").json()[
        "intento"
    ]
    base = f"/api/alumno/intentos/{intento_id}"

    cuerpo = navegador.get(f"{base}/actual").json()
    vistos = []
    while cuerpo["pregunta"] is not None:
        pregunta = cuerpo["pregunta"]
        assert pregunta["audio_url"] is None
        assert pregunta["texto"] in TEXTOS
        # Ninguna otra pregunta viaja junto con la actual.
        crudo = json.dumps(cuerpo, ensure_ascii=False)
        presentes = [t for t in TEXTOS if json.dumps(t, ensure_ascii=False)[1:-1] in crudo]
        assert presentes == [pregunta["texto"]]
        assert navegador.get(f"/api/alumno/respuestas/{pregunta['ref']}/audio").status_code == 404
        vistos.append(pregunta["texto"])
        elegida = pregunta["alternativas"][0]["id"]
        cuerpo = navegador.enviar(
            f"{base}/responder", {"ref": pregunta["ref"], "alternativa_id": elegida}
        ).json()
    assert sorted(vistos) == sorted(TEXTOS)

    # En modalidad normal el texto sí viaja (y el primero dice «correcta»), pero
    # nunca qué alternativa es la correcta ni el puntaje.
    for _, _, contenido in navegador.anotadas:
        assert b"es_correcta" not in contenido
        assert b'"puntaje"' not in contenido


def test_la_busqueda_detectaria_una_fuga():
    """Control de la prueba: si el texto se colara, la búsqueda lo encontraría."""
    evaluacion = _preparar_evaluacion()
    pregunta = evaluacion.preguntas.get(orden=4)
    fuga = json.dumps({"texto": pregunta.texto, "es_correcta": True}).encode()
    motivos = [m for m, forma in _formas_prohibidas(evaluacion).items() if forma in fuga]
    assert "texto 4 (JSON ascii)" in motivos
    assert "es_correcta" in motivos
