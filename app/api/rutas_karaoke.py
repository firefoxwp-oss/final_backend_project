"""Rutas del Modo Karaoke (RutasKaraoke): letra sincronizada por palabra."""

import json
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.rutas_trabajos import _job_propio
from app.archivos import DIR_SRT, ruta_letra
from app.auth import get_current_user, get_db
from app.models import User
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


@router.get("/jobs/{job_id}/letra", response_model=LetraRespuesta)
def obtener_letra(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lineas de la cancion con el inicio y el fin de cada palabra (Pb-5)."""
    job = _job_propio(job_id, db, current_user)
    if job.status != "done":
        raise HTTPException(
            status_code=409, detail="La canción todavía no está lista"
        )
    ruta = ruta_letra(job.id)
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    ruta_srt = os.path.join(DIR_SRT, f"{job.id}.srt")
    if os.path.exists(ruta_srt):
        return _letra_desde_srt(ruta_srt)
    raise HTTPException(status_code=404, detail="La canción no tiene letra")
