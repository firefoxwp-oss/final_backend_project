"""Pruebas del trabajador de la cola (Trabajador)."""

import os
import uuid
from datetime import datetime, timedelta, timezone

from app.archivos import DIR_VIDEOS, crear_directorios
from app.cola.cola_trabajos import ColaTrabajos
from app.cola.trabajador import Trabajador
from app.models import Job


def _encolar(db, usuario, minutos_atras):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        created_at=datetime.now(timezone.utc)
        - timedelta(minutes=minutos_atras),
    )
    return ColaTrabajos(db).encolar(job)


def test_procesa_un_trabajo_a_la_vez_por_orden_de_llegada(
    db, usuario, monkeypatch
):
    tercero = _encolar(db, usuario, 1)
    primero = _encolar(db, usuario, 10)
    segundo = _encolar(db, usuario, 5)
    procesados = []

    def procesar_falso(self, cola, job):
        en_proceso = cola.db.query(Job).filter(Job.status == "running")
        procesados.append((job.id, en_proceso.count()))
        cola.marcar_terminado(job, [], "instrumental")

    monkeypatch.setattr(Trabajador, "procesar", procesar_falso)
    trabajador = Trabajador()

    while trabajador.procesar_siguiente():
        pass

    assert [job_id for job_id, _ in procesados] == [primero, segundo, tercero]
    assert all(en_proceso == 1 for _, en_proceso in procesados)


def test_sin_trabajos_en_cola_no_procesa_nada():
    assert Trabajador().procesar_siguiente() is False


def test_trabajo_sin_archivo_subido_termina_con_error(db, usuario):
    job_id = _encolar(db, usuario, 0)

    Trabajador().procesar_siguiente()

    job = db.get(Job, job_id)
    db.refresh(job)
    assert job.status == "error"
    assert "archivo subido" in job.error


def test_al_arrancar_limpia_los_trabajos_interrumpidos(db, usuario):
    job_id = _encolar(db, usuario, 0)
    job = db.get(Job, job_id)
    job.status = "running"
    db.commit()
    crear_directorios()
    parcial = os.path.join(DIR_VIDEOS, f"{job_id}_sin_audio.mp4")
    with open(parcial, "wb") as f:
        f.write(b"parcial")

    Trabajador().recuperar_trabajos_tras_reinicio()

    db.refresh(job)
    assert job.status == "error"
    assert not os.path.exists(parcial)
