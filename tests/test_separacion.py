"""Pruebas del modelo de separacion con respaldo automatico (Pb-12)."""

import os
import threading
import time

import psutil
import pytest
import requests

from app.cola.trabajador import Trabajador
from app.separacion.separador_demucs import SeparadorDemucs
from app.separacion.separador_spleeter import SeparadorSpleeter

LIMITE_MEMORIA_GB = 6


def _subir(servidor, token, ruta):
    with open(ruta, "rb") as archivo:
        return requests.post(
            f"{servidor}/procesar-video/",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("cancion.mp4", archivo)},
            data={"video_type": "instrumental"},
            timeout=60,
        ).json()["job_id"]


def _estado(servidor, token, job_id):
    return requests.get(
        f"{servidor}/jobs/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ).json()


def _memoria_del_arbol(proceso):
    """Memoria residente del proceso y de todos sus subprocesos, en bytes."""
    total = 0
    for p in [proceso, *proceso.children(recursive=True)]:
        try:
            total += p.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


@pytest.mark.lento
def test_si_demucs_falla_el_trabajo_termina_con_spleeter(
    servidor, token, video_corto
):
    # Un modelo inexistente hace que Demucs termine con error, como en un
    # fallo real del modelo principal
    trabajador = Trabajador(
        separadores=[
            SeparadorDemucs(modelo="modelo_inexistente"),
            SeparadorSpleeter(),
        ]
    )
    job_id = _subir(servidor, token, video_corto)

    assert trabajador.procesar_siguiente() is True

    estado = _estado(servidor, token, job_id)
    assert estado["status"] == "done"
    assert estado["separation_model"] == "spleeter"
    assert estado["artifacts"]["audio_vocals"]
    assert estado["artifacts"]["audio_instrumental"]


@pytest.mark.lento
def test_el_procesamiento_no_supera_6_gb_de_memoria(
    servidor, token, video_largo
):
    job_id = _subir(servidor, token, video_largo)
    actual = psutil.Process(os.getpid())
    pico = 0
    hilo = threading.Thread(target=Trabajador().procesar_siguiente)
    hilo.start()
    while hilo.is_alive():
        pico = max(pico, _memoria_del_arbol(actual))
        time.sleep(0.5)

    print(f"\nPico de memoria del procesamiento: {pico / 1024**3:.2f} GB")
    assert _estado(servidor, token, job_id)["separation_model"] == "demucs"
    assert pico < LIMITE_MEMORIA_GB * 1024**3
