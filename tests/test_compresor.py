"""Pistas comprimidas para el Modo Karaoke (Pb-6, Sp-13)."""

import os
import subprocess

from app.karaoke.compresor_audio import CompresorAudio


def test_comprime_el_wav_en_m4a(tmp_path):
    wav = tmp_path / "pista.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=20",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(wav),
        ],
        check=True,
    )
    destino = CompresorAudio().comprimir(str(wav), str(tmp_path / "pista.m4a"))
    # 20 s de audio: unas 10 veces mas liviano que el WAV
    assert os.path.getsize(destino) < os.path.getsize(wav) / 5
    duracion = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            destino,
        ],
        text=True,
    )
    assert abs(float(duracion) - 20) < 0.2
