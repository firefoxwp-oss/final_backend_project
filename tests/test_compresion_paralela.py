"""Las pistas del Modo Karaoke se comprimen mientras se transcribe (mejora del
Sprint 3, RR-03, Sp-21)."""

import os
import time

from app.cola.trabajador import Trabajador
from app.models import Media
from app.separacion.separador_voz import ResultadoSeparacion
from tests.test_cambiador_tono import _tono
from tests.test_subida import _subir


class _SeparadorRapido:
    """Separacion simulada: dos tonos en lugar de la voz y el instrumental."""

    nombre = "demucs"

    def separar(self, audio, carpeta, ejecutar):
        voz = os.path.join(carpeta, "vocals.wav")
        instrumental = os.path.join(carpeta, "no_vocals.wav")
        _tono(voz, 330, segundos=8)
        _tono(instrumental, 440, segundos=8)
        return ResultadoSeparacion(voz=voz, instrumental=instrumental)


class _CompresorLento:
    """Compresor que tarda: registra cuando empieza y termina."""

    def __init__(self):
        self.fin = None

    def comprimir(self, wav, destino, ejecutar=None):
        time.sleep(1)
        with open(destino, "wb") as f:
            f.write(b"m4a")
        self.fin = time.perf_counter()
        return destino


def test_la_compresion_no_retrasa_la_transcripcion(
    servidor, token, video_corto, db, monkeypatch
):
    job_id = _subir(servidor, token, video_corto).json()["job_id"]
    trabajador = Trabajador(separadores=[_SeparadorRapido()])
    compresor = _CompresorLento()
    trabajador.compresor = compresor
    inicio_transcripcion = []

    def transcribir(self, cola, job, *args):
        inicio_transcripcion.append(time.perf_counter())
        return None

    monkeypatch.setattr(
        Trabajador, "transcribir_y_generar_karaoke", transcribir
    )

    assert trabajador.procesar_siguiente() is True

    # La transcripcion empieza antes de que terminen las pistas comprimidas
    assert inicio_transcripcion[0] < compresor.fin
    tipos = {
        m.type for m in db.query(Media).filter(Media.job_id == job_id).all()
    }
    assert {"playback_instrumental", "playback_vocals"} <= tipos
