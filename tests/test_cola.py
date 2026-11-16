"""Pruebas de la cola de trabajos (ColaTrabajos)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.cola.cola_trabajos import ColaTrabajos
from app.models import Job


def _trabajo(usuario, minutos_atras=0, **campos):
    return Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        created_at=datetime.now(timezone.utc)
        - timedelta(minutes=minutos_atras),
        **campos,
    )


def test_encolar_deja_el_trabajo_en_cola(db, usuario):
    job = _trabajo(usuario)
    job_id = ColaTrabajos(db).encolar(job)

    guardado = db.get(Job, job_id)
    assert guardado.status == "queued"
    assert guardado.progress == 0


def test_siguiente_toma_el_trabajo_mas_antiguo(db, usuario):
    cola = ColaTrabajos(db)
    nuevo = cola.encolar(_trabajo(usuario, minutos_atras=1))
    antiguo = cola.encolar(_trabajo(usuario, minutos_atras=5))

    assert cola.siguiente().id == antiguo
    db.rollback()
    assert nuevo != antiguo


def test_siguiente_ignora_trabajos_que_no_estan_en_cola(db, usuario):
    cola = ColaTrabajos(db)
    db.add(_trabajo(usuario, status="done"))
    db.add(_trabajo(usuario, status="error"))
    db.commit()

    assert cola.siguiente() is None


def test_marcar_procesando_registra_el_inicio(db, usuario):
    cola = ColaTrabajos(db)
    job = db.get(Job, cola.encolar(_trabajo(usuario)))

    cola.marcar_procesando(job)

    assert job.status == "running"
    assert job.started_at is not None


def test_marcar_terminado_exige_todos_los_archivos(db, usuario, tmp_path):
    cola = ColaTrabajos(db)
    job = db.get(Job, cola.encolar(_trabajo(usuario)))
    existente = tmp_path / "instrumental.wav"
    existente.write_bytes(b"x")

    with pytest.raises(RuntimeError, match="Faltan archivos"):
        cola.marcar_terminado(
            job, [str(existente), str(tmp_path / "falta.wav")], "karaoke"
        )

    cola.marcar_terminado(job, [str(existente)], "karaoke")
    assert job.status == "done"
    assert job.progress == 100


def test_recuperar_tras_reinicio(db, usuario):
    cola = ColaTrabajos(db)
    en_proceso = _trabajo(usuario, status="running")
    en_cola = _trabajo(usuario, status="queued")
    db.add_all([en_proceso, en_cola])
    db.commit()

    interrumpidos = cola.recuperar_trabajos_tras_reinicio()

    assert interrumpidos == [en_proceso.id]
    db.refresh(en_proceso)
    db.refresh(en_cola)
    assert en_proceso.status == "error"
    assert "reinicio" in en_proceso.error
    assert en_cola.status == "queued"
