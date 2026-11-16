"""Rutas de los archivos generados y utilidades comunes del procesamiento.

Las usan la API y el trabajador de la cola, que se ejecutan en procesos
distintos pero comparten la carpeta `media/`.
"""

import os
import subprocess

DIR_PROYECTO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

DIR_VIDEOS = os.path.join("media", "videos")
DIR_AUDIOS = os.path.join("media", "audios")
DIR_SRT = os.path.join("media", "subtitulos", "subtitulos_srt")
DIR_ASS = os.path.join("media", "subtitulos", "subtitulos_ass")


def crear_directorios() -> None:
    for carpeta in (DIR_VIDEOS, DIR_AUDIOS, DIR_SRT, DIR_ASS):
        os.makedirs(carpeta, exist_ok=True)


def ruta_origen(job_id: str, extension: str) -> str:
    """Archivo subido por el usuario, a la espera de ser procesado."""
    return os.path.join(DIR_VIDEOS, f"{job_id}_origen{extension}")


def ruta_instrumental(job_id: str) -> str:
    return os.path.join(DIR_VIDEOS, f"{job_id}_sin_voces.mp4")


def ruta_karaoke(job_id: str) -> str:
    return os.path.join(DIR_VIDEOS, f"{job_id}_karaoke.mp4")


def ejecutable_venv(venv: str, nombre: str) -> str:
    """Ejecutable de un entorno de Python del proyecto, en Windows o en Linux."""
    if os.name == "nt":
        return os.path.join(DIR_PROYECTO, venv, "Scripts", f"{nombre}.exe")
    return os.path.join(DIR_PROYECTO, venv, "bin", nombre)


def duracion_segundos(path: str):
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path.replace("\\", "/"),
            ],
            text=True,
            timeout=30,
        )
        return float(out.strip())
    except Exception:
        return None
