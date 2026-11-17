"""Procesa canciones de referencia y mide su tiempo (mejora del Sprint 3,
meta RR-03: una cancion de 4 minutos en 20 minutos o menos).

Sube cada archivo por la API, como lo haria un usuario, espera a que el
trabajador lo termine y muestra el tiempo total y el de cada etapa, que el
trabajador guarda en media/metadatos/tiempos (en el servidor, la carpeta del
proyecto). Uso:
    python -m tests.medir_procesamiento <url_api> <correo> <clave> <archivo>...
"""

import json
import sys
import time

import requests

from app.archivos import ruta_tiempos

META_SEGUNDOS = 20 * 60


def _subir(api: str, token: str, archivo: str) -> str:
    with open(archivo, "rb") as f:
        respuesta = requests.post(
            f"{api}/procesar-video/",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (archivo.replace("\\", "/").split("/")[-1], f)},
            data={"video_type": "karaoke"},
            timeout=300,
        )
    respuesta.raise_for_status()
    return respuesta.json()["job_id"]


def _esperar(api: str, token: str, job_id: str) -> dict:
    while True:
        estado = requests.get(
            f"{api}/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        ).json()
        if estado["status"] in ("done", "error", "cancelled"):
            return estado
        time.sleep(10)


def main(api: str, correo: str, clave: str, archivos: list) -> bool:
    token = requests.post(
        f"{api}/login",
        json={"email": correo, "password": clave},
        timeout=30,
    ).json()["access_token"]
    cumple = True
    for archivo in archivos:
        job_id = _subir(api, token, archivo)
        estado = _esperar(api, token, job_id)
        if estado["status"] != "done":
            print(f"{archivo}: {estado['status']}")
            cumple = False
            continue
        with open(ruta_tiempos(job_id), encoding="utf-8") as f:
            tiempos = json.load(f)
        total = tiempos["total_segundos"]
        cumple &= total <= META_SEGUNDOS
        print(
            f"{archivo} ({tiempos['duracion_audio_segundos']} s): "
            f"{total / 60:.1f} min (meta {META_SEGUNDOS // 60} min)"
        )
        for etapa in tiempos["etapas"]:
            print(
                f"  {etapa['etapa']:24} {etapa['segundos']:7.1f} s "
                f"{etapa['porcentaje']:5.1f} %"
            )
    print("cumple RR-03" if cumple else "NO cumple RR-03")
    return cumple


if __name__ == "__main__":
    sys.exit(
        0 if main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]) else 1
    )
