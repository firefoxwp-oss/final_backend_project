"""Entrega de las pistas comprimidas del Modo Karaoke (Pb-6, Sp-14)."""

import os
import subprocess
import uuid

import requests

from app.archivos import ruta_pista_comprimida, ruta_pista_wav
from app.auth import get_password_hash
from app.models import Job, Media, User


def _cancion(db, usuario, segundos=5):
    """Cancion terminada con sus WAV, como las procesadas antes de Sp-13."""
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        status="done",
        video_type="karaoke",
    )
    db.add(job)
    db.commit()
    for pista in ("instrumental", "voz"):
        wav = ruta_pista_wav(job.id, pista)
        os.makedirs(os.path.dirname(wav), exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={segundos}",
                "-ac",
                "2",
                wav,
            ],
            check=True,
        )
    return job


def _descargar(servidor, token, tipo, job_id):
    return requests.get(
        f"{servidor}/descargar/{tipo}/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )


def test_entrega_las_dos_pistas_comprimidas(servidor, token, usuario, db):
    job = _cancion(db, usuario)
    for tipo, pista in (
        ("instrumental_comprimido", "instrumental"),
        ("voz_comprimida", "voz"),
    ):
        respuesta = _descargar(servidor, token, tipo, job.id)
        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == "audio/mp4"
        wav = os.path.getsize(ruta_pista_wav(job.id, pista))
        assert 0 < len(respuesta.content) < wav / 5
        assert os.path.exists(ruta_pista_comprimida(job.id, pista))


def test_la_pista_generada_se_conserva_y_se_registra(
    servidor, token, usuario, db
):
    job = _cancion(db, usuario)
    _descargar(servidor, token, "voz_comprimida", job.id)
    _descargar(servidor, token, "voz_comprimida", job.id)
    tipos = [m.type for m in db.query(Media).filter(Media.job_id == job.id)]
    assert tipos == ["playback_vocals"]


def test_sin_pista_o_de_otro_usuario(servidor, token, usuario, db):
    sin_audio = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="x.mp4",
        status="done",
    )
    db.add(sin_audio)
    otro = User(name="O", email="o@test.com", password=get_password_hash("x"))
    db.add(otro)
    db.commit()
    ajena = _cancion(db, otro)
    respuesta = _descargar(servidor, token, "voz_comprimida", sin_audio.id)
    assert respuesta.status_code == 404
    ajena_resp = _descargar(servidor, token, "voz_comprimida", ajena.id)
    assert ajena_resp.status_code == 403
