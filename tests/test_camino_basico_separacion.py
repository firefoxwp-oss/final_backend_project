"""Caminos básicos de la separación con respaldo automático (Pb-12).

Cada prueba recorre uno de los tres caminos independientes del grafo de
flujo de Trabajador.separar (complejidad ciclomática 3).
"""

import pytest

from app.cola.trabajador import Trabajador


class _Separador:
    def __init__(self, nombre, falla):
        self.nombre = nombre
        self.falla = falla
        self.llamado = False

    def separar(self, audio, carpeta, ejecutar):
        self.llamado = True
        if self.falla:
            raise RuntimeError(f"{self.nombre} no pudo separar")
        return f"pistas de {self.nombre}"


def _trabajador(falla_demucs, falla_spleeter):
    demucs = _Separador("demucs", falla_demucs)
    spleeter = _Separador("spleeter", falla_spleeter)
    return Trabajador(separadores=[demucs, spleeter]), demucs, spleeter


def test_c1_demucs_separa_y_no_se_usa_el_respaldo():
    trabajador, _, spleeter = _trabajador(False, False)

    resultado, modelo = trabajador.separar("job", "audio.wav", "salida")

    assert (resultado, modelo) == ("pistas de demucs", "demucs")
    assert not spleeter.llamado


def test_c2_si_demucs_falla_separa_spleeter():
    trabajador, demucs, _ = _trabajador(True, False)

    resultado, modelo = trabajador.separar("job", "audio.wav", "salida")

    assert demucs.llamado
    assert (resultado, modelo) == ("pistas de spleeter", "spleeter")


def test_c3_si_ambos_fallan_el_trabajo_termina_con_error():
    trabajador, demucs, spleeter = _trabajador(True, True)

    with pytest.raises(RuntimeError, match="spleeter"):
        trabajador.separar("job", "audio.wav", "salida")
    assert demucs.llamado and spleeter.llamado
