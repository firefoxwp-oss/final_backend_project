"""Cambio de tono de las pistas del Modo Karaoke (Pb-11).

Genera el instrumental o la voz guia de una cancion en otro tono, de -6 a +6
semitonos, sin cambiar su velocidad, con FFmpeg y la biblioteca rubberband.
Cada version se guarda en disco y en la tabla `tone_versions`: la primera vez
se genera y despues se reutiliza (RR-09).
"""

import os

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.archivos import (
    ruta_pista_comprimida,
    ruta_pista_wav,
    ruta_version_tono,
)
from app.karaoke.compresor_audio import BITRATE
from app.models import TONO_MAXIMO, Job, ToneVersion
from app.separacion.separador_voz import ejecutar_proceso

# Nombre de cada pista del Modo Karaoke en la tabla tone_versions
PISTAS = {"instrumental": "instrumental", "voz": "vocals"}


class CambiadorTono:
    def __init__(self, db: Session, ejecutar=ejecutar_proceso):
        self.db = db
        self.ejecutar = ejecutar

    def generar(self, job: Job, pista: str, semitonos: int) -> str:
        """Devuelve la ruta de la `pista` en el tono pedido; la genera solo
        si no existe todavia."""
        if pista not in PISTAS:
            raise ValueError(f"Pista no valida: {pista}")
        if semitonos == 0 or abs(semitonos) > TONO_MAXIMO:
            raise ValueError(
                f"El tono debe ir de -{TONO_MAXIMO} a +{TONO_MAXIMO} "
                "semitonos, sin el 0"
            )
        version = self._buscar(job.id, pista, semitonos)
        if version is not None and os.path.exists(version.path):
            return version.path

        destino = ruta_version_tono(job.id, pista, semitonos)
        self._convertir(self._origen(job.id, pista), destino, semitonos)
        if version is None:
            self._registrar(job.id, pista, semitonos, destino)
        return destino

    def _buscar(self, job_id: str, pista: str, semitonos: int):
        return (
            self.db.query(ToneVersion)
            .filter(
                ToneVersion.job_id == job_id,
                ToneVersion.track == PISTAS[pista],
                ToneVersion.semitones == semitonos,
            )
            .one_or_none()
        )

    def _origen(self, job_id: str, pista: str) -> str:
        """El WAV separado da mejor calidad; si ya no esta, la pista
        comprimida."""
        for ruta in (
            ruta_pista_wav(job_id, pista),
            ruta_pista_comprimida(job_id, pista),
        ):
            if os.path.exists(ruta):
                return ruta
        raise FileNotFoundError(f"No se encontro la pista {pista}")

    def _convertir(self, origen: str, destino: str, semitonos: int) -> None:
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        # Se escribe aparte y se renombra: una conversion cortada no queda
        # como version valida
        temporal = f"{destino}.parcial.m4a"
        factor = 2 ** (semitonos / 12)
        self.ejecutar(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                origen,
                "-vn",
                "-af",
                f"rubberband=pitch={factor:.6f}:pitchq=quality",
                "-c:a",
                "aac",
                "-b:a",
                BITRATE,
                "-movflags",
                "+faststart",
                temporal,
                "-y",
            ]
        )
        if not os.path.exists(temporal):
            raise RuntimeError(f"No se genero la version de tono {destino}")
        os.replace(temporal, destino)

    def _registrar(self, job_id, pista, semitonos, destino) -> None:
        self.db.add(
            ToneVersion(
                job_id=job_id,
                semitones=semitonos,
                track=PISTAS[pista],
                path=destino,
            )
        )
        try:
            self.db.commit()
        except IntegrityError:
            # Otra peticion registro la misma version al mismo tiempo
            self.db.rollback()
