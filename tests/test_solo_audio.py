"""Pruebas del procesamiento de archivos solo de audio (mejora del Sprint
1: los MP3 terminaban con error)."""

import subprocess

import pytest

from app.archivos import duracion_segundos, tiene_video
from app.cola.trabajador import Trabajador
from tests.test_subida import _estado, _subir


def _ffmpeg(*argumentos):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *argumentos, "-y"], check=True
    )


@pytest.fixture(scope="module")
def audio_mp3(tmp_path_factory):
    """MP3 de 8 s con un tono."""
    ruta = tmp_path_factory.mktemp("audios") / "cancion.mp3"
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=8", str(ruta))
    return ruta


@pytest.fixture(scope="module")
def mp3_con_caratula(tmp_path_factory, audio_mp3):
    """MP3 con la caratula del disco, que FFmpeg ve como un video."""
    carpeta = tmp_path_factory.mktemp("caratula")
    imagen = carpeta / "caratula.jpg"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=300x300",
        "-frames:v",
        "1",
        str(imagen),
    )
    ruta = carpeta / "con_caratula.mp3"
    _ffmpeg(
        "-i",
        str(audio_mp3),
        "-i",
        str(imagen),
        "-map",
        "0:a",
        "-map",
        "1:v",
        "-c",
        "copy",
        "-disposition:v",
        "attached_pic",
        str(ruta),
    )
    return ruta


def test_distingue_un_video_de_un_audio(
    video_corto, audio_mp3, mp3_con_caratula
):
    assert tiene_video(str(video_corto))
    assert not tiene_video(str(audio_mp3))
    assert not tiene_video(str(mp3_con_caratula))


def test_un_audio_recibe_un_fondo_de_su_misma_duracion(audio_mp3, tmp_path):
    destino = tmp_path / "sin_audio.mp4"

    Trabajador().extraer_video("prueba", str(audio_mp3), str(destino), 8)

    assert tiene_video(str(destino))
    assert duracion_segundos(str(destino)) == pytest.approx(8, abs=0.5)


def test_un_audio_sin_duracion_conocida_termina_con_error(audio_mp3, tmp_path):
    with pytest.raises(ValueError, match="duracion"):
        Trabajador().extraer_video(
            "prueba", str(audio_mp3), str(tmp_path / "x.mp4"), None
        )


@pytest.mark.lento
def test_el_trabajador_procesa_un_mp3(servidor, token, audio_mp3):
    job_id = _subir(servidor, token, audio_mp3, nombre="cancion.mp3").json()[
        "job_id"
    ]

    assert Trabajador().procesar_siguiente() is True

    estado = _estado(servidor, token, job_id)
    assert estado["status"] == "done"
    assert estado["artifacts"]["video_instrumental"]
    assert estado["artifacts"]["audio_vocals"]
