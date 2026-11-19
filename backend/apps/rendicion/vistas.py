"""Endpoints del alumno para rendir (sección 11): ``/api/alumno/…``.

Todas las consultas se filtran por el alumno de la sesión (sección 10): un
intento, una respuesta o una evaluación de otra persona responden 404, igual
que si no existieran, y el intento queda en la bitácora como acceso denegado.
"""

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.models import Accion
from apps.auditoria.servicios import registrar, registrar_acceso_denegado
from apps.core.errores import ErrorApi
from apps.cuentas.limites import LimitePorUsuario
from apps.cuentas.permisos import PERMISOS_DEL_ALUMNO
from apps.evaluaciones.models import AsignacionPrueba, EstadoEvaluacion, Evaluacion, Modalidad

from . import motor
from .models import Intento, Respuesta
from .serializadores import (
    SerializadorIniciar,
    SerializadorRef,
    SerializadorResponder,
    SerializadorVoz,
    estado_para_alumno,
)
from .servicios import crear_intento

# Un alumno nunca tiene tantas pruebas; el tope evita respuestas desmedidas.
MAXIMO_EVALUACIONES_LISTADAS = 100

ESTADOS_VISIBLES = (EstadoEvaluacion.PUBLICADA, EstadoEvaluacion.CERRADA)


class VistaAlumno(APIView):
    """Base de los endpoints del alumno: sesión completa, rol alumno y límite general."""

    permission_classes = PERMISOS_DEL_ALUMNO
    throttle_classes = [LimitePorUsuario]


def no_encontrado(peticion, modelo, pk) -> NotFound:
    """404 para lo que no es del alumno. Si existe y es de otro, queda registrado."""
    if modelo.objects.filter(pk=pk).exists():
        registrar_acceso_denegado(
            peticion, motivo="objeto_ajeno", objeto_tipo=modelo._meta.label
        )
    return NotFound()


def _validar(serializador, peticion) -> dict:
    datos = serializador(data=peticion.data)
    datos.is_valid(raise_exception=True)
    return datos.validated_data


def _respuesta_de(estado: motor.Estado, ahora) -> Response:
    restante = motor.restante(estado.respuesta, ahora) if estado.respuesta else None
    return Response(estado_para_alumno(estado.intento, estado.respuesta, restante))


# --- Pruebas asignadas -------------------------------------------------------------------


def estado_para_el_alumno(evaluacion: Evaluacion, intento: Intento | None, ahora) -> str:
    if intento is not None:
        return "EN_CURSO" if intento.en_curso else "TERMINADA"
    if evaluacion.estado == EstadoEvaluacion.CERRADA or ahora > evaluacion.fin:
        return "VENCIDA"
    if ahora < evaluacion.inicio:
        return "PROXIMA"
    return "DISPONIBLE"


class VistaEvaluacionesDelAlumno(VistaAlumno):
    """``GET alumno/evaluaciones``: las pruebas asignadas y en qué va cada una."""

    def get(self, request):
        ahora = timezone.now()
        asignaciones = list(
            AsignacionPrueba.objects.filter(
                alumno=request.user, evaluacion__estado__in=ESTADOS_VISIBLES
            )
            .select_related("evaluacion")
            .annotate(preguntas=Count("evaluacion__preguntas"))
            .order_by("-evaluacion__inicio")[:MAXIMO_EVALUACIONES_LISTADAS]
        )
        intentos = {
            intento.evaluacion_id: intento
            for intento in Intento.objects.filter(
                alumno=request.user,
                evaluacion_id__in=[asignacion.evaluacion_id for asignacion in asignaciones],
            )
        }
        resultados = []
        for asignacion in asignaciones:
            evaluacion = asignacion.evaluacion
            intento = intentos.get(evaluacion.id)
            resultados.append(
                {
                    "id": str(evaluacion.id),
                    "titulo": evaluacion.titulo,
                    "asignatura": evaluacion.asignatura,
                    "instrucciones": evaluacion.instrucciones,
                    "inicio": evaluacion.inicio,
                    "fin": evaluacion.fin,
                    "modalidad": asignacion.modalidad,
                    "preguntas": asignacion.preguntas,
                    "estado": estado_para_el_alumno(evaluacion, intento, ahora),
                    "intento": str(intento.id) if intento else None,
                }
            )
        return Response({"resultados": resultados})


# --- Iniciar -----------------------------------------------------------------------------


class VistaIniciar(VistaAlumno):
    """``POST alumno/evaluaciones/{id}/iniciar``: crea el intento (regla 1)."""

    def post(self, request, evaluacion_id):
        datos = _validar(SerializadorIniciar, request)
        ahora = timezone.now()
        asignaciones = AsignacionPrueba.objects.filter(
            evaluacion_id=evaluacion_id,
            alumno=request.user,
            evaluacion__estado__in=ESTADOS_VISIBLES,
        )
        # Fuera de la transacción: el registro del acceso denegado no se
        # deshace junto con ella.
        if not asignaciones.exists():
            raise no_encontrado(request, Evaluacion, evaluacion_id)
        with transaction.atomic():
            # La asignación queda bloqueada: dos clics en "Empezar" a la vez
            # no crean dos intentos (el segundo ve el que dejó el primero).
            asignacion = (
                asignaciones.select_for_update(of=("self",)).select_related("evaluacion").first()
            )
            if asignacion is None:
                raise NotFound()
            evaluacion = asignacion.evaluacion

            if Intento.objects.filter(evaluacion=evaluacion, alumno=request.user).exists():
                raise ErrorApi(
                    "intento_existente",
                    "Ya iniciaste esta prueba. Vuelve a ella desde la lista de pruebas.",
                    estado=status.HTTP_409_CONFLICT,
                )
            if evaluacion.estado != EstadoEvaluacion.PUBLICADA or ahora > evaluacion.fin:
                raise ErrorApi(
                    "prueba_terminada",
                    "El plazo para rendir esta prueba ya terminó.",
                    estado=status.HTTP_409_CONFLICT,
                )
            if ahora < evaluacion.inicio:
                raise ErrorApi(
                    "prueba_no_comenzada",
                    "Esta prueba todavía no comienza.",
                    estado=status.HTTP_409_CONFLICT,
                )

            voz = datos.get("voz") or ""
            if asignacion.modalidad == Modalidad.NOTIA and not voz:
                raise serializers.ValidationError(
                    {"voz": ["Elige la voz que leerá tus preguntas."]}
                )

            intento = crear_intento(asignacion, voz=voz, ahora=ahora)
            if intento.voz and request.user.voz_preferida != intento.voz:
                request.user.voz_preferida = intento.voz
                request.user.save(update_fields=["voz_preferida"])
            registrar(
                Accion.INTENTO_INICIADO,
                actor=request.user,
                peticion=request,
                objeto=intento,
                detalle={"modalidad": intento.modalidad},
            )
        return Response(
            {"intento": str(intento.id), "estado": intento.estado, "modalidad": intento.modalidad},
            status=status.HTTP_201_CREATED,
        )


# --- El intento ----------------------------------------------------------------------------


class VistaIntento(VistaAlumno):
    """Base de las operaciones sobre un intento del alumno."""

    def operar(self, request, intento_id, operacion):
        consulta = Intento.objects.filter(pk=intento_id, alumno=request.user)
        estado = motor.operar(consulta, operacion)
        if estado is None:
            raise no_encontrado(request, Intento, intento_id)
        return estado


class VistaActual(VistaIntento):
    """``GET alumno/intentos/{id}/actual``: la pregunta que corresponde ahora."""

    def get(self, request, intento_id):
        ahora = timezone.now()
        estado = self.operar(request, intento_id, lambda intento: motor.presentar(intento, ahora))
        return _respuesta_de(estado, ahora)


class VistaResponder(VistaIntento):
    """``POST alumno/intentos/{id}/responder`` con ``{ref, alternativa_id}``."""

    def post(self, request, intento_id):
        datos = _validar(SerializadorResponder, request)
        ahora = timezone.now()
        estado = self.operar(
            request,
            intento_id,
            lambda intento: motor.responder(intento, datos["ref"], datos["alternativa_id"], ahora),
        )
        return _respuesta_de(estado, ahora)


class VistaPasar(VistaIntento):
    """``POST alumno/intentos/{id}/pasar`` con ``{ref}``."""

    def post(self, request, intento_id):
        datos = _validar(SerializadorRef, request)
        ahora = timezone.now()
        estado = self.operar(
            request, intento_id, lambda intento: motor.pasar(intento, datos["ref"], ahora)
        )
        return _respuesta_de(estado, ahora)


class VistaCambiarVoz(VistaIntento):
    """``PATCH alumno/intentos/{id}/voz``: otra voz, sin reiniciar el tiempo (regla 11)."""

    def patch(self, request, intento_id):
        datos = _validar(SerializadorVoz, request)

        def cambiar(intento):
            if not intento.en_curso:
                raise motor.PreguntaNoDisponible()
            if intento.modalidad != Modalidad.NOTIA:
                raise ErrorApi(
                    "sin_audio",
                    "En la modalidad normal las preguntas no tienen audio.",
                    estado=status.HTTP_409_CONFLICT,
                )
            intento.voz = datos["voz"]
            intento.save(update_fields=["voz"])
            return motor.en_curso(intento)

        self.operar(request, intento_id, cambiar)
        if request.user.voz_preferida != datos["voz"]:
            request.user.voz_preferida = datos["voz"]
            request.user.save(update_fields=["voz_preferida"])
        return Response({"voz": datos["voz"]})


class VistaRepeticion(VistaAlumno):
    """``POST alumno/respuestas/{ref}/repeticion``: el alumno volvió a escuchar."""

    def post(self, request, ref):
        ahora = timezone.now()
        intento_id = (
            Respuesta.objects.filter(pk=ref, intento__alumno=request.user)
            .values_list("intento_id", flat=True)
            .first()
        )
        if intento_id is None:
            raise no_encontrado(request, Respuesta, ref)
        consulta = Intento.objects.filter(pk=intento_id, alumno=request.user)
        motor.operar(consulta, lambda intento: motor.contar_repeticion(intento, ref, ahora))
        return Response(status=status.HTTP_204_NO_CONTENT)
