"""Separacion de voz con Spleeter (2 stems), en el entorno de TensorFlow.
Es el modelo de respaldo."""

import os

from app.archivos import ejecutable_venv, ruta_modelo
from app.separacion.separador_voz import (
    ResultadoSeparacion,
    SeparadorVoz,
    ejecutar_proceso,
)


class SeparadorSpleeter(SeparadorVoz):
    nombre = "spleeter"

    def __init__(self):
        self.ejecutable = os.getenv("SPLEETER_BIN") or ejecutable_venv(
            "venv", "spleeter"
        )
        # Spleeter busca el modelo 2stems dentro de MODEL_PATH
        self.modelos = os.getenv("SPLEETER_MODELOS") or ruta_modelo("spleeter")

    def separar(
        self, audio: str, carpeta_salida: str, ejecutar=ejecutar_proceso
    ) -> ResultadoSeparacion:
        ejecutar(
            [
                self.ejecutable,
                "separate",
                "-p",
                "spleeter:2stems",
                "-o",
                carpeta_salida,
                audio,
            ],
            {**os.environ, "MODEL_PATH": self.modelos},
        )
        base = os.path.join(
            carpeta_salida, os.path.splitext(os.path.basename(audio))[0]
        )
        return self.verificar(
            ResultadoSeparacion(
                voz=os.path.join(base, "vocals.wav"),
                instrumental=os.path.join(base, "accompaniment.wav"),
            )
        )
