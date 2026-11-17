"""Pruebas de caja negra de la subida en segundo plano (Pb-1)."""

import os
import time

import pytest
import requests

from app.cola.trabajador import Trabajador


def _subir(servidor, token, ruta, nombre="cancion.mp4", **campos):
    with open(ruta, "rb") as archivo:
        return requests.post(
            f"{servidor}/procesar-video/",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            files={"file": (nombre, archivo)},
            data=campos,
            timeout=60,
        )


def _estado(servidor, token, job_id):
    return requests.get(
        f"{servidor}/jobs/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ).json()


def test_la_subida_responde_en_menos_de_2_s_con_el_trabajo_en_cola(
    servidor, token, video_corto
):
    inicio = time.perf_counter()
    respuesta = _subir(servidor, token, video_corto)
    duracion = time.perf_counter() - inicio

    assert respuesta.status_code == 202
    assert duracion < 2
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "queued"
    assert _estado(servidor, token, cuerpo["job_id"])["status"] == "queued"


def test_rechaza_un_formato_no_permitido(servidor, token, tmp_path):
    texto = tmp_path / "notas.txt"
    texto.write_text("no es un video")

    respuesta = _subir(servidor, token, texto, nombre="notas.txt")

    assert respuesta.status_code == 400


def test_rechaza_un_tipo_de_video_no_valido(servidor, token, video_corto):
    respuesta = _subir(servidor, token, video_corto, video_type="otro")

    assert respuesta.status_code == 400


def test_exige_iniciar_sesion(servidor, video_corto):
    respuesta = _subir(servidor, None, video_corto)

    assert respuesta.status_code in (401, 403)


@pytest.mark.lento
def test_el_trabajador_completa_el_procesamiento(servidor, token, video_corto):
    job_id = _subir(servidor, token, video_corto).json()["job_id"]

    # El cliente ya no participa: el trabajador procesa el trabajo solo
    assert Trabajador().procesar_siguiente() is True

    estado = _estado(servidor, token, job_id)
    assert estado["status"] == "done"
    assert estado["progress"] == 100
    assert estado["separation_model"] == "demucs"
    assert estado["artifacts"]["video_instrumental"]
    assert estado["artifacts"]["audio_vocals"]
    assert estado["artifacts"]["audio_instrumental"]
    assert not os.path.exists(f"output_{job_id}")
