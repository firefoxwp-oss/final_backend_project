"""Interfaz comun de los modelos de separacion de voz."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ResultadoSeparacion:
    voz: str
    instrumental: str


class SeparadorVoz(ABC):
    """Separa la voz del acompanamiento musical de un archivo de audio."""

    nombre: str

    @abstractmethod
    def separar(self, audio: str, carpeta_salida: str) -> ResultadoSeparacion:
        """Genera la voz y el instrumental en `carpeta_salida` y devuelve sus rutas."""
