"""Generacion y reutilizacion de las pistas en otro tono (Pb-11, Sp-9)."""

import os
import subprocess
import uuid

import numpy as np
import pytest

from app.archivos import (
    eliminar_rutas,
    archivos_del_trabajo,
    duracion_segundos,
    ruta_pista_wav,
)
from app.karaoke.cambiador_tono import CambiadorTono
from app.models import Job, ToneVersion

FRECUENCIA = 8000


def _tono(ruta, hz, segundos=4):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={hz}:duration={segundos}",
            "-ac",
            "2",
            ruta,
            "-y",
        ],
        check=True,
    )


def _frecuencia_dominante(ruta):
    """Frecuencia con mas energia del audio, decodificado con FFmpeg."""
    pcm = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            ruta,
            "-ac",
            "1",
            "-ar",
            str(FRECUENCIA),
            "-f",
            "f32le",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    muestras = np.frombuffer(pcm, dtype=np.float32)
    espectro = np.abs(np.fft.rfft(muestras))
    return np.argmax(espectro) * FRECUENCIA / len(muestras)


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
    _tono(ruta_pista_wav(job.id, "instrumental"), 440)
    _tono(ruta_pista_wav(job.id, "voz"), 330)
    yield job
    eliminar_rutas(archivos_del_trabajo(job.id))


# 440 Hz por 2 elevado a (semitonos / 12)
@pytest.mark.parametrize(
    "semitonos, esperada", [(6, 622.3), (-6, 311.1), (4, 554.4)]
)
def test_cambia_el_tono_sin_cambiar_la_duracion(
    db, cancion, semitonos, esperada
):
    ruta = CambiadorTono(db).generar(cancion, "instrumental", semitonos)

    assert ruta.endswith(f"instrumental_{semitonos:+d}.m4a")
    assert _frecuencia_dominante(ruta) == pytest.approx(esperada, rel=0.02)
    assert duracion_segundos(ruta) == pytest.approx(4, abs=0.1)


def test_la_version_se_genera_una_vez_y_se_reutiliza(db, cancion):
    conversiones = []

    def ejecutar(cmd):
        conversiones.append(cmd)
        subprocess.run(cmd, check=True)

    cambiador = CambiadorTono(db, ejecutar)
    primera = cambiador.generar(cancion, "voz", 2)
    segunda = cambiador.generar(cancion, "voz", 2)

    assert primera == segunda
    assert len(conversiones) == 1
    version = db.query(ToneVersion).one()
    assert (version.track, version.semitones) == ("vocals", 2)
    assert _frecuencia_dominante(primera) == pytest.approx(370, rel=0.02)


def test_si_falta_el_archivo_lo_vuelve_a_generar(db, cancion):
    cambiador = CambiadorTono(db)
    ruta = cambiador.generar(cancion, "instrumental", -3)
    os.remove(ruta)

    assert cambiador.generar(cancion, "instrumental", -3) == ruta
    assert os.path.exists(ruta)
    assert db.query(ToneVersion).count() == 1


@pytest.mark.parametrize("pista, semitonos", [("voz", 0), ("voz", 7)])
def test_rechaza_un_tono_fuera_del_rango(db, cancion, pista, semitonos):
    with pytest.raises(ValueError):
        CambiadorTono(db).generar(cancion, pista, semitonos)


def test_rechaza_una_pista_que_no_existe(db, cancion):
    with pytest.raises(ValueError):
        CambiadorTono(db).generar(cancion, "bateria", 2)
