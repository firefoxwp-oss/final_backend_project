"""Rutas del Modo Karaoke (RutasKaraoke): letra sincronizada por palabra y
pistas en otro tono."""

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.rutas_trabajos import _asegurar_comprimida, _job_propio
from app.archivos import DIR_SRT, ruta_letra, ruta_pista_comprimida
from app.auth import get_current_user, get_db
from app.karaoke.cambiador_tono import PISTAS, CambiadorTono
from app.models import TONO_MAXIMO, Job, User
from app.schemas import LetraRespuesta
from app.subtitles import parse_srt_word_level
from app.whisperx_run import construir_letra

router = APIRouter(tags=["karaoke"])


def _letra_desde_srt(ruta_srt: str) -> dict:
    """Letra de las canciones procesadas antes del Sprint 2, que solo tienen
    el SRT palabra por palabra."""
    palabras = [
        {
            "word": p["text"],
            "start": p["start_ms"] / 1000,
            "end": p["end_ms"] / 1000,
        }
        for p in parse_srt_word_level(ruta_srt)
    ]
    return construir_letra([{"words": palabras}])


def _cancion_terminada(job_id: str, db: Session, usuario: User) -> Job:
    job = _job_propio(job_id, db, usuario)
    if job.status != "done":
        raise HTTPException(
            status_code=409, detail="La canción todavía no está lista"
        )
    return job


@router.get("/jobs/{job_id}/letra", response_model=LetraRespuesta)
def obtener_letra(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lineas de la cancion con el inicio y el fin de cada palabra (Pb-5)."""
    job = _cancion_terminada(job_id, db, current_user)
    ruta = ruta_letra(job.id)
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    ruta_srt = os.path.join(DIR_SRT, f"{job.id}.srt")
    if os.path.exists(ruta_srt):
        return _letra_desde_srt(ruta_srt)
    raise HTTPException(status_code=404, detail="La canción no tiene letra")


# Funcion sincrona: FastAPI la ejecuta en su grupo de hilos, de modo que el
# instrumental y la voz se generan a la vez y la API sigue respondiendo
@router.get("/jobs/{job_id}/tono/{semitonos}/{pista}")
def obtener_pista_en_tono(
    job_id: str,
    semitonos: int,
    pista: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pista del Modo Karaoke (`instrumental` o `voz`) en el tono pedido, de
    -6 a +6 semitonos; con 0, la pista original (Pb-11)."""
    if pista not in PISTAS:
        raise HTTPException(status_code=422, detail="Pista no válida")
    if abs(semitonos) > TONO_MAXIMO:
        raise HTTPException(
            status_code=422,
            detail=f"El tono va de -{TONO_MAXIMO} a +{TONO_MAXIMO} semitonos",
        )
    job = _cancion_terminada(job_id, db, current_user)
    if semitonos == 0:
        _asegurar_comprimida(
            db,
            job,
            (
                "instrumental_comprimido"
                if pista == "instrumental"
                else "voz_comprimida"
            ),
        )
        ruta = ruta_pista_comprimida(job.id, pista)
    else:
        try:
            ruta = CambiadorTono(db).generar(job, pista, semitonos)
        except FileNotFoundError:
            ruta = None
    if ruta is None or not os.path.exists(ruta):
        raise HTTPException(
            status_code=404, detail="La canción no tiene esta pista"
        )
    return FileResponse(
        ruta,
        media_type="audio/mp4",
        filename=f"{job.id}_{pista}_{semitonos:+d}.m4a",
        content_disposition_type="inline",
    )
