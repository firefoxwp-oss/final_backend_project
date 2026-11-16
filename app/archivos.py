"""Rutas de los archivos generados y utilidades comunes del procesamiento.

Las usan la API y el trabajador de la cola, que se ejecutan en procesos
distintos pero comparten la carpeta `media/`.
"""

import glob
import os
import shutil
import subprocess

DIR_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIR_VIDEOS = os.path.join("media", "videos")
DIR_AUDIOS = os.path.join("media", "audios")
DIR_SRT = os.path.join("media", "subtitulos", "subtitulos_srt")
DIR_ASS = os.path.join("media", "subtitulos", "subtitulos_ass")
# Letra sincronizada por palabra del Modo Karaoke (JSON)
DIR_LETRA = os.path.join("media", "subtitulos", "letra")

# Modelos preentrenados guardados en el proyecto, para procesar sin conexion
DIR_MODELOS = os.path.join(DIR_PROYECTO, "pretrained_models")


def ruta_modelo(nombre: str, *partes: str) -> str:
    """Archivos de un modelo en `pretrained_models/<nombre>/modelo`."""
    return os.path.join(DIR_MODELOS, nombre, "modelo", *partes)


def crear_directorios() -> None:
    for carpeta in (DIR_VIDEOS, DIR_AUDIOS, DIR_SRT, DIR_ASS, DIR_LETRA):
        os.makedirs(carpeta, exist_ok=True)


def ruta_origen(job_id: str, extension: str) -> str:
    """Archivo subido por el usuario, a la espera de ser procesado."""
    return os.path.join(DIR_VIDEOS, f"{job_id}_origen{extension}")


def ruta_instrumental(job_id: str) -> str:
    return os.path.join(DIR_VIDEOS, f"{job_id}_sin_voces.mp4")


def ruta_karaoke(job_id: str) -> str:
    return os.path.join(DIR_VIDEOS, f"{job_id}_karaoke.mp4")


# Pistas comprimidas del Modo Karaoke: (archivo, WAV de origen)
PISTAS_COMPRIMIDAS = {
    "instrumental": ("instrumental.m4a", "accompaniment.wav"),
    "voz": ("vocals.m4a", "vocals.wav"),
}


def ruta_pista_comprimida(job_id: str, pista: str) -> str:
    return os.path.join(DIR_AUDIOS, job_id, PISTAS_COMPRIMIDAS[pista][0])


def ruta_pista_wav(job_id: str, pista: str) -> str:
    return os.path.join(DIR_AUDIOS, job_id, PISTAS_COMPRIMIDAS[pista][1])


def ruta_letra(job_id: str) -> str:
    return os.path.join(DIR_LETRA, f"{job_id}.json")


def archivos_del_trabajo(job_id: str) -> list:
    """Archivos y carpetas que un trabajo deja en disco (completos o no)."""
    rutas = glob.glob(os.path.join(DIR_VIDEOS, f"{job_id}_*"))
    rutas += [
        os.path.join(DIR_AUDIOS, f"{job_id}.wav"),
        os.path.join(DIR_AUDIOS, job_id),
        os.path.join(DIR_SRT, f"{job_id}.srt"),
        os.path.join(DIR_ASS, f"{job_id}.ass"),
        ruta_letra(job_id),
        os.path.join("media", "metadatos", "karaoke", job_id),
        f"output_{job_id}",
    ]
    return rutas


def eliminar_rutas(rutas) -> None:
    for ruta in rutas:
        if os.path.isdir(ruta):
            shutil.rmtree(ruta, ignore_errors=True)
        elif os.path.exists(ruta):
            try:
                os.remove(ruta)
            except OSError:
                pass


def ejecutable_venv(venv: str, nombre: str) -> str:
    """Ejecutable de un entorno de Python del proyecto (Windows o Linux)."""
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
