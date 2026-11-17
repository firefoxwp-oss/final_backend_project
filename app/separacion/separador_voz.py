"""Interfaz comun de los modelos de separacion de voz."""

import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ResultadoSeparacion:
    voz: str
    instrumental: str


def ejecutar_proceso(cmd, entorno=None) -> None:
    subprocess.run(cmd, check=True, env=entorno)


class SeparadorVoz(ABC):
    """Separa la voz del acompanamiento musical de un archivo de audio."""

    nombre: str

    @abstractmethod
    def separar(
        self, audio: str, carpeta_salida: str, ejecutar=ejecutar_proceso
    ) -> ResultadoSeparacion:
        """Genera la voz y el instrumental en `carpeta_salida`.

        `ejecutar(cmd, entorno)` lanza el modelo; el trabajador pasa uno que
        lo detiene si el trabajo se cancela. Lanza una excepcion si el modelo
        falla.
        """

    @staticmethod
    def verificar(resultado: ResultadoSeparacion) -> ResultadoSeparacion:
        for ruta in (resultado.voz, resultado.instrumental):
            if not os.path.exists(ruta):
                raise RuntimeError(f"El modelo no genero {ruta}")
        return resultado
