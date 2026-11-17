"""Tiempo de cada etapa del procesamiento (mejora del Sprint 3, RR-03).

El trabajador avisa cada cambio de etapa; al terminar el trabajo, el medidor
informa cuanto tardo cada una y lo guarda en `media/metadatos/tiempos`, para
comparar canciones y saber que etapa conviene acelerar.
"""

import json
import os
import time

from app.archivos import ruta_tiempos


class MedidorEtapas:
    def __init__(self, job_id: str, reloj=time.perf_counter):
        self.job_id = job_id
        self.reloj = reloj
        self.inicio = reloj()
        self.etapas = []
        self._actual = None

    def etapa(self, nombre: str) -> None:
        """Empieza la etapa `nombre` y cierra la anterior."""
        ahora = self.reloj()
        self._cerrar(ahora)
        self._actual = (nombre, ahora)

    def _cerrar(self, ahora: float) -> None:
        if self._actual is not None:
            nombre, desde = self._actual
            self.etapas.append({"etapa": nombre, "segundos": ahora - desde})
            self._actual = None

    def terminar(self, duracion_audio=None) -> dict:
        """Cierra la ultima etapa, guarda el resumen y lo devuelve."""
        ahora = self.reloj()
        self._cerrar(ahora)
        total = ahora - self.inicio
        resumen = {
            "job_id": self.job_id,
            "duracion_audio_segundos": duracion_audio,
            "total_segundos": round(total, 1),
            "etapas": [
                {
                    "etapa": e["etapa"],
                    "segundos": round(e["segundos"], 1),
                    "porcentaje": (
                        round(100 * e["segundos"] / total, 1) if total else 0
                    ),
                }
                for e in self.etapas
            ],
        }
        ruta = ruta_tiempos(self.job_id)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(resumen, f, ensure_ascii=False, indent=2)
        detalle = ", ".join(
            f"{e['etapa']} {e['segundos']} s ({e['porcentaje']} %)"
            for e in resumen["etapas"]
        )
        print(
            f"[job {self.job_id}] tiempos: total {resumen['total_segundos']}"
            f" s; {detalle}"
        )
        return resumen
