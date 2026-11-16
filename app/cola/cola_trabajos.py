"""Cola de trabajos.

La cola es la propia tabla `jobs`: un trabajo en estado `queued` espera su
turno y el trabajador toma siempre el mas antiguo.
"""

import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Job, Media


def _ahora():
    return datetime.now(timezone.utc)


class ColaTrabajos:
    def __init__(self, db: Session):
        self.db = db

    def encolar(self, job: Job) -> str:
        job.status = "queued"
        job.stage = "en_cola"
        job.progress = 0
        self.db.add(job)
        self.db.commit()
        return job.id

    def siguiente(self):
        """Trabajo en cola mas antiguo, o None si la cola esta vacia."""
        return (
            self.db.query(Job)
            .filter(Job.status == "queued")
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )

    def marcar_procesando(self, job: Job) -> None:
        job.status = "running"
        job.stage = "extrayendo_audio"
        job.progress = 5
        job.started_at = _ahora()
        self.db.commit()

    def avanzar(self, job: Job, stage: str, progress: int) -> None:
        """Publica el progreso real del pipeline para que los clientes lo consulten."""
        job.stage = stage
        job.progress = progress
        self.db.commit()
        print(f"[job {job.id}] {progress}% - {stage}")

    def registrar_archivo(self, job: Job, path: str, formato: str, tipo: str) -> None:
        self.db.add(
            Media(
                name=os.path.basename(path),
                path=path,
                format=formato,
                type=tipo,
                job_id=job.id,
            )
        )
        self.db.commit()

    def marcar_terminado(self, job: Job, archivos: list, video_type: str) -> None:
        """Cierra el trabajo solo si existen todos sus archivos obligatorios."""
        faltantes = [p for p in archivos if not os.path.exists(p)]
        if faltantes:
            raise RuntimeError(f"Faltan archivos generados: {', '.join(faltantes)}")
        job.video_type = video_type
        job.status = "done"
        job.stage = "completado"
        job.progress = 100
        job.error = None
        job.finished_at = _ahora()
        self.db.commit()

    def marcar_error(self, job: Job, mensaje: str) -> None:
        job.status = "error"
        job.error = mensaje
        job.finished_at = _ahora()
        self.db.commit()
