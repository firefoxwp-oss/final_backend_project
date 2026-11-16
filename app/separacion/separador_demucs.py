"""Separacion de voz con Demucs v4 (Hybrid Transformer), en el entorno de
PyTorch. Es el modelo principal."""

import os

from app.archivos import ejecutable_venv, ruta_modelo
from app.separacion.separador_voz import (
    ResultadoSeparacion,
    SeparadorVoz,
    ejecutar_proceso,
)

MODELO = os.getenv("DEMUCS_MODEL", "htdemucs")


class SeparadorDemucs(SeparadorVoz):
    nombre = "demucs"

    def __init__(self, modelo: str = MODELO):
        self.modelo = modelo
        self.python = os.getenv("DEMUCS_PY") or ejecutable_venv(
            "venv_torch", "python"
        )
        # Carpeta con los pesos del modelo; Demucs no descarga nada
        self.repositorio = os.getenv("DEMUCS_REPO") or ruta_modelo("demucs")

    def separar(
        self, audio: str, carpeta_salida: str, ejecutar=ejecutar_proceso
    ) -> ResultadoSeparacion:
        ejecutar(
            [
                self.python,
                "-m",
                "demucs",
                "-n",
                self.modelo,
                "--repo",
                self.repositorio,
                "--two-stems",
                "vocals",
                "-d",
                "cpu",
                "-o",
                carpeta_salida,
                audio,
            ],
            # Los pesos oficiales guardan la clase del modelo, que torch.load
            # rechaza por defecto; es lo mismo que hace Demucs al descargarlos
            {**os.environ, "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"},
        )
        base = os.path.join(
            carpeta_salida,
            self.modelo,
            os.path.splitext(os.path.basename(audio))[0],
        )
        return self.verificar(
            ResultadoSeparacion(
                voz=os.path.join(base, "vocals.wav"),
                instrumental=os.path.join(base, "no_vocals.wav"),
            )
        )
