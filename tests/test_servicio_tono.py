"""Servicio que entrega las pistas en el tono pedido (Pb-11, Sp-10)."""

import time
import uuid

import pytest
import requests

from app.archivos import archivos_del_trabajo, eliminar_rutas, ruta_pista_wav
from app.auth import get_password_hash
from app.models import Job, ToneVersion, User
from tests.test_cambiador_tono import _tono


@pytest.fixture
def cancion(db, usuario):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        status="done",
    )
    db.add(job)
    db.commit()
    _tono(ruta_pista_wav(job.id, "instrumental"), 440, segundos=20)
    _tono(ruta_pista_wav(job.id, "voz"), 330, segundos=20)
    yield job
    eliminar_rutas(archivos_del_trabajo(job.id))


def _pista(servidor, token, job_id, semitonos, pista):
    return requests.get(
        f"{servidor}/jobs/{job_id}/tono/{semitonos}/{pista}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )


def test_entrega_la_pista_en_el_tono_pedido(servidor, token, cancion, db):
    respuesta = _pista(servidor, token, cancion.id, -2, "voz")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "audio/mp4"
    assert len(respuesta.content) > 10_000
    version = db.query(ToneVersion).filter_by(job_id=cancion.id).one()
    assert (version.track, version.semitones) == ("vocals", -2)


def test_un_tono_ya_generado_se_entrega_al_instante(servidor, token, cancion):
    inicio = time.perf_counter()
    _pista(servidor, token, cancion.id, 3, "instrumental")
    primera = time.perf_counter() - inicio
    inicio = time.perf_counter()
    respuesta = _pista(servidor, token, cancion.id, 3, "instrumental")
    segunda = time.perf_counter() - inicio

    assert respuesta.status_code == 200
    assert segunda < 3
    assert segunda < primera


def test_con_cero_semitonos_entrega_la_pista_original(
    servidor, token, cancion, db
):
    respuesta = _pista(servidor, token, cancion.id, 0, "instrumental")

    assert respuesta.status_code == 200
    assert db.query(ToneVersion).count() == 0


@pytest.mark.parametrize(
    "semitonos, pista", [(7, "voz"), (-7, "instrumental"), (2, "bateria")]
)
def test_rechaza_tonos_y_pistas_no_validos(
    servidor, token, cancion, semitonos, pista
):
    respuesta = _pista(servidor, token, cancion.id, semitonos, pista)

    assert respuesta.status_code == 422


def test_una_cancion_sin_terminar_no_tiene_tonos(servidor, token, cancion, db):
    cancion.status = "running"
    db.commit()

    assert _pista(servidor, token, cancion.id, 2, "voz").status_code == 409


def test_no_entrega_las_pistas_de_otro_usuario(servidor, cancion, db):
    db.add(
        User(
            name="Otra",
            email="otra@test.com",
            password=get_password_hash("secreta123"),
        )
    )
    db.commit()
    otro = requests.post(
        f"{servidor}/login",
        json={"email": "otra@test.com", "password": "secreta123"},
        timeout=10,
    ).json()["access_token"]

    assert _pista(servidor, otro, cancion.id, 2, "voz").status_code == 403


def test_sin_audio_separado_responde_404(servidor, token, cancion):
    eliminar_rutas(archivos_del_trabajo(cancion.id))

    assert _pista(servidor, token, cancion.id, 2, "voz").status_code == 404
