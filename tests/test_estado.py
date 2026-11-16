"""Pruebas de caja negra del estado y la posicion en la cola (Pb-2)."""

import time
import uuid
from datetime import datetime, timedelta, timezone

import requests

from app.auth import get_password_hash
from app.models import Job, User


def _trabajo(db, usuario, minutos_atras, **campos):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        created_at=datetime.now(timezone.utc)
        - timedelta(minutes=minutos_atras),
        **campos,
    )
    db.add(job)
    db.commit()
    return job.id


def _estado(servidor, token, job_id):
    return requests.get(
        f"{servidor}/jobs/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )


def test_posicion_por_orden_de_llegada(servidor, token, db, usuario):
    segundo = _trabajo(db, usuario, 5, status="queued")
    primero = _trabajo(db, usuario, 10, status="queued")
    tercero = _trabajo(db, usuario, 1, status="queued")

    posiciones = [
        _estado(servidor, token, j).json()["queue_position"]
        for j in (primero, segundo, tercero)
    ]

    assert posiciones == [1, 2, 3]


def test_en_proceso_muestra_etapa_y_avance_sin_posicion(
    servidor, token, db, usuario
):
    job_id = _trabajo(
        db,
        usuario,
        0,
        status="running",
        stage="separando_voces",
        progress=15,
    )

    estado = _estado(servidor, token, job_id).json()

    assert estado["status"] == "running"
    assert estado["queue_position"] is None
    assert estado["stage"] == "separando_voces"
    assert estado["progress"] == 15


def test_la_cola_avanza_cuando_un_trabajo_sale(servidor, token, db, usuario):
    primero = _trabajo(db, usuario, 10, status="queued")
    segundo = _trabajo(db, usuario, 5, status="queued")
    assert _estado(servidor, token, segundo).json()["queue_position"] == 2

    db.get(Job, primero).status = "running"
    db.commit()

    assert _estado(servidor, token, segundo).json()["queue_position"] == 1


def test_el_historial_incluye_la_posicion(servidor, token, db, usuario):
    _trabajo(db, usuario, 10, status="queued")
    _trabajo(db, usuario, 5, status="done", progress=100)

    historial = requests.get(
        f"{servidor}/jobs",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ).json()

    posiciones = {j["status"]: j["queue_position"] for j in historial}
    assert posiciones == {"queued": 1, "done": None}


def test_cada_consulta_responde_en_menos_de_500_ms(
    servidor, token, db, usuario
):
    job_id = _trabajo(db, usuario, 0, status="queued")
    _estado(servidor, token, job_id)

    tiempos = []
    for _ in range(10):
        inicio = time.perf_counter()
        assert _estado(servidor, token, job_id).status_code == 200
        tiempos.append(time.perf_counter() - inicio)

    assert max(tiempos) < 0.5


def test_no_muestra_trabajos_de_otro_usuario(servidor, token, db):
    otro = User(
        name="Otro",
        email="otro@test.com",
        password=get_password_hash("secreta123"),
    )
    db.add(otro)
    db.commit()
    ajeno = _trabajo(db, otro, 0, status="queued")

    assert _estado(servidor, token, ajeno).status_code == 403
