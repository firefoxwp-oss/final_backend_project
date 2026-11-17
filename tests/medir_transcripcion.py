"""Mide el tiempo de la transcripcion con cada modelo de Whisper (mejora del
Sprint 2).

Transcribe el mismo audio con cada modelo, con la configuracion del .env, e
informa el tiempo, el factor de tiempo real (tiempo / duracion) y las palabras
reconocidas. Uso:
    python -m tests.medir_transcripcion <voz.wav> [modelo ...]
"""

import json
import os
import subprocess
import sys
import tempfile
import time

from dotenv import load_dotenv

from app.archivos import DIR_PROYECTO, duracion_segundos, ejecutable_venv

MODELOS = ["large-v2", "large-v3-turbo"]


def medir(audio: str, modelo: str, carpeta: str) -> dict:
    letra = os.path.join(carpeta, f"{modelo}.json")
    inicio = time.perf_counter()
    subprocess.run(
        [
            ejecutable_venv("venv_torch", "python"),
            os.path.join(DIR_PROYECTO, "app", "whisperx_run.py"),
            "--audio",
            audio,
            "--srt",
            os.path.join(carpeta, f"{modelo}.srt"),
            "--letra",
            letra,
            "--model",
            modelo,
        ],
        cwd=DIR_PROYECTO,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    segundos = time.perf_counter() - inicio
    with open(letra, encoding="utf-8") as archivo:
        lineas = json.load(archivo)["lineas"]
    palabras = [p["texto"] for linea in lineas for p in linea["palabras"]]
    return {"modelo": modelo, "segundos": segundos, "palabras": palabras}


def main(audio: str, modelos: list) -> None:
    load_dotenv(os.path.join(DIR_PROYECTO, ".env"))
    duracion = duracion_segundos(audio)
    print(f"audio: {os.path.basename(audio)} ({duracion:.0f} s)")
    with tempfile.TemporaryDirectory() as carpeta:
        for modelo in modelos:
            r = medir(audio, modelo, carpeta)
            print(
                f"{modelo:16} {r['segundos']:7.1f} s  "
                f"x{r['segundos'] / duracion:.2f} tiempo real  "
                f"{len(r['palabras'])} palabras"
            )
            print("  " + " ".join(r["palabras"][:25]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or MODELOS)
