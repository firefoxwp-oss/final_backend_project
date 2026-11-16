"""Pruebas de caja negra de la cancelacion de trabajos (Pb-3)."""

import os
import threading
import time
import uuid

import pytest
import requests

from app.archivos import archivos_del_trabajo
from app.auth import get_password_hash
from app.cola.trabajador import Trabajador
from app.models import Job, User


def _cabecera(token):
    return {"Authorization": f"Bearer {token}"}


def _subir(servidor, token, ruta):
    with open(ruta, "rb") as archivo:
        respuesta = requests.post(
            f"{servidor}/procesar-video/",
            headers=_cabecera(token),
            files={"file": ("cancion.mp4", archivo)},
            data={"video_type": "instrumental"},
            timeout=60,
        )
    return respuesta.json()["job_id"]


def _cancelar(servidor, token, job_id):
    return requests.post(
        f"{servidor}/jobs/{job_id}/cancelar",
        headers=_cabecera(token),
        timeout=10,
    )


def _estado(servidor, token, job_id):
    return requests.get(
        f"{servidor}/jobs/{job_id}", headers=_cabecera(token), timeout=10
    ).json()


def _archivos_restantes(job_id):
    return [r for r in archivos_del_trabajo(job_id) if os.path.exists(r)]


def test_cancelar_en_cola_lo_saca_y_actualiza_posiciones(
    servidor, token, video_corto
):
    primero = _subir(servidor, token, video_corto)
    segundo = _subir(servidor, token, video_corto)
    assert _estado(servidor, token, segundo)["queue_position"] == 2

    respuesta = _cancelar(servidor, token, primero)

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "cancelled"
    assert _estado(servidor, token, primero)["status"] == "cancelled"
    assert _estado(servidor, token, segundo)["queue_position"] == 1
    assert _archivos_restantes(primero) == []


def test_no_se_cancela_un_trabajo_terminado(servidor, token, db, usuario):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        status="done",
        progress=100,
    )
    db.add(job)
    db.commit()

    assert _cancelar(servidor, token, job.id).status_code == 409


def test_no_se_cancela_un_trabajo_de_otro_usuario(servidor, token, db):
    otro = User(
        name="Otro",
        email="otro@test.com",
        password=get_password_hash("secreta123"),
    )
    db.add(otro)
    db.commit()
    ajeno = Job(
        id=str(uuid.uuid4()),
        user_id=otro.id,
        source_filename="cancion.mp4",
        status="queued",
    )
    db.add(ajeno)
    db.commit()

    assert _cancelar(servidor, token, ajeno.id).status_code == 403
    db.refresh(ajeno)
    assert ajeno.status == "queued"


def test_trabajo_inexistente(servidor, token):
    assert _cancelar(servidor, token, str(uuid.uuid4())).status_code == 404


@pytest.mark.lento
def test_cancelar_en_proceso_lo_detiene_y_la_cola_continua(
    servidor, token, video_largo
):
    en_proceso = _subir(servidor, token, video_largo)
    siguiente = _subir(servidor, token, video_largo)
    hilo = threading.Thread(target=Trabajador().procesar_siguiente)
    hilo.start()
    for _ in range(120):
        if _estado(servidor, token, en_proceso)["stage"] == "separando_voces":
            break
        time.sleep(0.5)

    inicio = time.perf_counter()
    respuesta = _cancelar(servidor, token, en_proceso)
    hilo.join(timeout=30)
    duracion = time.perf_counter() - inicio

    assert respuesta.status_code == 200
    assert not hilo.is_alive()
    assert duracion < 5
    assert _estado(servidor, token, en_proceso)["status"] == "cancelled"
    assert _archivos_restantes(en_proceso) == []
    assert _estado(servidor, token, siguiente)["queue_position"] == 1
    assert _cancelar(servidor, token, siguiente).status_code == 200
