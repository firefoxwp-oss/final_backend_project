"""Separacion de voz con Spleeter (2 stems), en el entorno de TensorFlow."""

import os
import subprocess

from app.persistencia.archivos import ejecutable_venv
from app.separacion.separador_voz import ResultadoSeparacion, SeparadorVoz


class SeparadorSpleeter(SeparadorVoz):
    nombre = "spleeter"

    def __init__(self):
        self.ejecutable = os.getenv("SPLEETER_BIN") or ejecutable_venv("venv", "spleeter")

    def separar(self, audio: str, carpeta_salida: str) -> ResultadoSeparacion:
        subprocess.run(
            [self.ejecutable, "separate", "-p", "spleeter:2stems", "-o", carpeta_salida,
             audio],
            check=True,
        )
        base = os.path.join(carpeta_salida, os.path.splitext(os.path.basename(audio))[0])
        resultado = ResultadoSeparacion(
            voz=os.path.join(base, "vocals.wav"),
            instrumental=os.path.join(base, "accompaniment.wav"),
        )
        if not os.path.exists(resultado.instrumental):
            raise RuntimeError("Spleeter no genero el instrumental")
        return resultado
