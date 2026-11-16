"""Servicio que entrega la letra sincronizada (Pb-5, Sp-8)."""

import json
import os
import time
import uuid

import requests

from app.archivos import DIR_SRT, crear_directorios, ruta_letra
from app.auth import get_password_hash
from app.models import Job, User

LETRA = {
    "lineas": [
        {
            "inicio": 1.0,
            "fin": 2.0,
            "palabras": [
                {"texto": "Hola", "inicio": 1.0, "fin": 1.4},
                {"texto": "mundo", "inicio": 1.5, "fin": 2.0},
            ],
        }
    ]
}


def _trabajo(db, usuario, status="done"):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        status=status,
    )
    db.add(job)
    db.commit()
    crear_directorios()
    return job


def _letra(servidor, token, job_id):
    return requests.get(
        f"{servidor}/jobs/{job_id}/letra",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )


def test_entrega_la_letra_sincronizada(servidor, token, usuario, db):
    job = _trabajo(db, usuario)
    with open(ruta_letra(job.id), "w", encoding="utf-8") as f:
        json.dump(LETRA, f)
    inicio = time.perf_counter()
    respuesta = _letra(servidor, token, job.id)
    assert respuesta.status_code == 200
    assert respuesta.json() == LETRA
    assert time.perf_counter() - inicio < 0.5


def test_canciones_anteriores_usan_el_srt(servidor, token, usuario, db):
    job = _trabajo(db, usuario)
    with open(
        os.path.join(DIR_SRT, f"{job.id}.srt"), "w", encoding="utf-8"
    ) as f:
        f.write(
            "1\n00:00:01,000 --> 00:00:01,400\nHola\n\n"
            "2\n00:00:01,500 --> 00:00:02,000\nmundo\n"
        )
    assert _letra(servidor, token, job.id).json() == LETRA


def test_solo_canciones_terminadas_y_con_letra(servidor, token, usuario, db):
    en_proceso = _trabajo(db, usuario, "running")
    assert _letra(servidor, token, en_proceso.id).status_code == 409
    sin_letra = _trabajo(db, usuario)
    assert _letra(servidor, token, sin_letra.id).status_code == 404


def test_no_entrega_la_letra_de_otro_usuario(servidor, token, db):
    otro = User(
        name="Otra", email="otra@test.com", password=get_password_hash("x")
    )
    db.add(otro)
    db.commit()
    job = _trabajo(db, otro)
    with open(ruta_letra(job.id), "w", encoding="utf-8") as f:
        json.dump(LETRA, f)
    assert _letra(servidor, token, job.id).status_code == 403
