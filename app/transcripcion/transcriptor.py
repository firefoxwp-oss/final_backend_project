"""Transcripcion de la voz con WhisperX, en el entorno de PyTorch."""

import os
import subprocess

from app.persistencia.archivos import DIR_PROYECTO, ejecutable_venv

SCRIPT_WHISPERX = os.path.join(DIR_PROYECTO, "app", "transcripcion", "whisperx_run.py")


def transcribir(audio: str, srt_path: str) -> None:
    """Genera el SRT con los tiempos de cada palabra de la voz."""
    python = os.getenv("WHISPERX_PY") or ejecutable_venv("venv_torch", "python")
    resultado = subprocess.run(
        [python, SCRIPT_WHISPERX, "--audio", audio, "--srt", srt_path],
        check=False,
        cwd=DIR_PROYECTO,
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(resultado.stderr)
        raise RuntimeError("WhisperX fallo")
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"WhisperX no genero el SRT: {srt_path}")
