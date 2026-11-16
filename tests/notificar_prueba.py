"""Envia una notificacion de fin de procesamiento a los celulares de un
usuario, para la prueba en el celular (Sp-6).

Crea un trabajo terminado de prueba y lo notifica con el mismo Notificador
que usa el trabajador. Uso: python -m tests.notificar_prueba <correo>
"""

import sys
import uuid
from datetime import datetime, timezone

from app.cola.cola_trabajos import ColaTrabajos
from app.database import SessionLocal
from app.models import Device, Job, User
from app.notificaciones.notificador import Notificador


def main(correo: str) -> None:
    with SessionLocal() as db:
        usuario = db.query(User).filter(User.email == correo).one()
        celulares = db.query(Device).filter(Device.user_id == usuario.id)
        print(f"celulares registrados: {celulares.count()}")
        ahora = datetime.now(timezone.utc)
        job = Job(
            id=str(uuid.uuid4()),
            user_id=usuario.id,
            source_filename="prueba_notificacion.mp4",
            status="done",
            stage="completado",
            progress=100,
            video_type="karaoke",
            finished_at=ahora,
        )
        db.add(job)
        db.commit()
        enviadas = Notificador().notificar_fin(ColaTrabajos(db), job)
        print(f"enviada a las {ahora.isoformat()} a {enviadas} celular(es)")


if __name__ == "__main__":
    main(sys.argv[1])
