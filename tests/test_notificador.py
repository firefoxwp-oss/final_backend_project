"""Notificacion de fin del procesamiento (Pb-4, Sp-3)."""

import uuid

import pytest
import requests

from app.cola.cola_trabajos import ColaTrabajos
from app.cola.trabajador import Trabajador
from app.models import Device, Job
from app.notificaciones.notificador import Notificador


class ConfiguracionFalsa:
    url_envio = "https://fcm.test/messages:send"

    def token_acceso(self):
        return "token-de-acceso"


class Respuesta:
    def __init__(self, status_code, mensaje=""):
        self.status_code = status_code
        self.text = mensaje

    def json(self):
        return {"error": {"message": self.text}}


class FcmFalso:
    """Registra los mensajes enviados y responde con el codigo indicado."""

    def __init__(self, codigo=200, mensaje=""):
        self.codigo, self.respuesta, self.enviados = codigo, mensaje, []

    def __call__(self, url, token_acceso, mensaje):
        self.enviados.append(mensaje)
        return Respuesta(self.codigo, self.respuesta)


def _trabajo(db, usuario, status="done"):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="mi_cancion.mp4",
        status=status,
    )
    db.add(job)
    db.commit()
    return job


def _celulares(db, usuario, cantidad=1):
    for k in range(cantidad):
        db.add(Device(user_id=usuario.id, token=f"token-{k}"))
    db.commit()


def test_notifica_a_cada_celular_del_usuario(db, usuario):
    _celulares(db, usuario, 2)
    job = _trabajo(db, usuario)
    fcm = FcmFalso()
    enviados = Notificador(ConfiguracionFalsa(), fcm).notificar_fin(
        ColaTrabajos(db), job
    )
    assert enviados == 2
    mensaje = fcm.enviados[0]
    assert mensaje["notification"]["title"] == "Tu canción está lista"
    assert "mi_cancion.mp4" in mensaje["notification"]["body"]
    assert mensaje["data"] == {"job_id": job.id, "status": "done"}
    assert job.notified_at is not None


def test_si_termina_con_error_la_notificacion_lo_indica(db, usuario):
    _celulares(db, usuario)
    job = _trabajo(db, usuario, "error")
    fcm = FcmFalso()
    Notificador(ConfiguracionFalsa(), fcm).notificar_fin(ColaTrabajos(db), job)
    titulo = fcm.enviados[0]["notification"]["title"]
    assert titulo == "No se pudo procesar tu canción"


def test_no_notifica_un_trabajo_cancelado(db, usuario):
    _celulares(db, usuario)
    job = _trabajo(db, usuario, "cancelled")
    fcm = FcmFalso()
    notificador = Notificador(ConfiguracionFalsa(), fcm)
    assert notificador.notificar_fin(ColaTrabajos(db), job) == 0
    assert fcm.enviados == []


def test_un_token_no_valido_se_elimina(db, usuario):
    _celulares(db, usuario)
    job = _trabajo(db, usuario)
    fcm = FcmFalso(404, "Requested entity was not found.")
    Notificador(ConfiguracionFalsa(), fcm).notificar_fin(ColaTrabajos(db), job)
    assert db.query(Device).count() == 0
    assert job.notified_at is None


def test_sin_conexion_el_trabajo_no_se_afecta(db, usuario):
    _celulares(db, usuario)
    job = _trabajo(db, usuario)

    def sin_conexion(*_):
        raise requests.ConnectionError("sin internet")

    notificador = Notificador(ConfiguracionFalsa(), sin_conexion)
    assert notificador.notificar_fin(ColaTrabajos(db), job) == 0
    assert job.status == "done"


def test_el_trabajador_notifica_al_terminar(db, usuario):
    """Un trabajo sin archivo subido termina con error y se notifica."""
    _celulares(db, usuario)
    job = Job(
        id=str(uuid.uuid4()), user_id=usuario.id, source_filename="x.mp4"
    )
    ColaTrabajos(db).encolar(job)
    fcm = FcmFalso()
    trabajador = Trabajador(notificador=Notificador(ConfiguracionFalsa(), fcm))
    assert trabajador.procesar_siguiente()
    assert fcm.enviados[0]["data"]["status"] == "error"


@pytest.mark.red
def test_firebase_rechaza_un_token_inexistente(db, usuario):
    """Envio real a FCM: un token inventado se rechaza y se elimina."""
    notificador = Notificador()
    if notificador.configuracion is None:
        pytest.skip("Firebase no esta configurado en el .env")
    _celulares(db, usuario)
    job = _trabajo(db, usuario)
    assert notificador.notificar_fin(ColaTrabajos(db), job) == 0
    assert db.query(Device).count() == 0
