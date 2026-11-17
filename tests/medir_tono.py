"""Mide el tiempo del cambio de tono (Pb-11, meta RR-09).

Genera a la vez el instrumental y la voz guia de una cancion en cada tono
pedido, como lo hace la aplicacion movil, y los vuelve a pedir para medir la
reutilizacion. Si la version ya existia, la borra antes para medir la
primera generacion. Uso:
    python -m tests.medir_tono <job_id> [semitonos ...]
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app.archivos import duracion_segundos, ruta_pista_wav
from app.database import SessionLocal
from app.karaoke.cambiador_tono import PISTAS, CambiadorTono
from app.models import Job, ToneVersion

META_GENERACION = 30
META_REUTILIZACION = 3


def _pista(job_id: str, pista: str, semitonos: int) -> str:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return CambiadorTono(db).generar(job, pista, semitonos)


def _ambas(job_id: str, semitonos: int) -> float:
    """Pide las dos pistas a la vez y devuelve el tiempo en segundos."""
    inicio = time.perf_counter()
    with ThreadPoolExecutor(len(PISTAS)) as hilos:
        list(hilos.map(lambda p: _pista(job_id, p, semitonos), PISTAS))
    return time.perf_counter() - inicio


def _borrar(job_id: str, semitonos: int) -> None:
    with SessionLocal() as db:
        versiones = db.query(ToneVersion).filter(
            ToneVersion.job_id == job_id, ToneVersion.semitones == semitonos
        )
        for version in versiones:
            if os.path.exists(version.path):
                os.remove(version.path)
        versiones.delete()
        db.commit()


def main(job_id: str, tonos: list) -> None:
    duracion = duracion_segundos(ruta_pista_wav(job_id, "instrumental"))
    print(f"cancion {job_id} ({duracion:.0f} s)")
    cumple = True
    for semitonos in tonos:
        _borrar(job_id, semitonos)
        primera = _ambas(job_id, semitonos)
        segunda = _ambas(job_id, semitonos)
        cumple &= primera <= META_GENERACION
        cumple &= segunda < META_REUTILIZACION
        print(
            f"{semitonos:+d} semitonos: genera {primera:.1f} s "
            f"(meta {META_GENERACION} s), reutiliza {segunda * 1000:.0f} ms "
            f"(meta {META_REUTILIZACION} s)"
        )
    print("cumple RR-09" if cumple else "NO cumple RR-09")


if __name__ == "__main__":
    main(sys.argv[1], [int(s) for s in sys.argv[2:]] or [2, -3, 6])
