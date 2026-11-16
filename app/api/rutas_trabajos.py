"""Rutas de trabajos (RutasTrabajos): subida, estado, historial y descargas."""

import array
import json
import os
import shutil
import tempfile
import uuid
import wave
import zipfile
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.archivos import (
    DIR_ASS,
    DIR_AUDIOS,
    DIR_SRT,
    crear_directorios,
    duracion_segundos,
    ruta_instrumental as _ruta_instrumental,
    ruta_karaoke as _ruta_karaoke,
    ruta_origen,
)
from app.auth import get_current_user, get_current_user_media, get_db
from app.cola.cola_trabajos import ColaTrabajos
from app.models import TIPOS_VIDEO, Job, Media, Project, User
from app.schemas import JobResponse, TrabajoEncolado

router = APIRouter(tags=["trabajos"])

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "1024")) * 1024 * 1024
MAX_DURACION_SEG = int(os.getenv("MAX_DURACION_MIN", "60")) * 60
EXTENSIONES_PERMITIDAS = {".mp4", ".avi", ".mkv", ".mp3", ".mov", ".m4v", ".webm"}


# --------------------------------------------------------------------- subida


@router.post("/procesar-video/", status_code=202, response_model=TrabajoEncolado)
def procesar_video(
    file: UploadFile = File(...),
    video_type: str = Form("karaoke"),
    job_id: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Guarda el archivo, lo encola y responde de inmediato con el id del trabajo.

    El procesamiento lo realiza el trabajador de la cola, independiente de esta
    peticion.
    """
    original_filename = file.filename or "video"
    extension = os.path.splitext(original_filename)[1].lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no permitido ({extension}). Admitidos: "
            + ", ".join(sorted(EXTENSIONES_PERMITIDAS)),
        )
    if video_type not in TIPOS_VIDEO:
        raise HTTPException(
            status_code=400,
            detail="Tipo de video no valido. Admitidos: " + ", ".join(TIPOS_VIDEO),
        )

    if project_id is not None:
        proyecto = db.query(Project).filter(Project.id == project_id).first()
        if proyecto is None or proyecto.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Proyecto no autorizado")

    # El cliente puede proponer el id del trabajo
    session_uuid = job_id or str(uuid.uuid4())
    try:
        uuid.UUID(session_uuid)
    except ValueError:
        session_uuid = str(uuid.uuid4())
    if db.query(Job).filter(Job.id == session_uuid).first():
        session_uuid = str(uuid.uuid4())

    crear_directorios()
    origen = ruta_origen(session_uuid, extension)

    try:
        # Guardado por bloques, sin cargar el archivo entero en memoria
        escrito = 0
        with open(origen, "wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                escrito += len(chunk)
                if escrito > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"El archivo supera el maximo de "
                        f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
                    )
                f.write(chunk)

        duracion = duracion_segundos(origen)
        if duracion is not None and duracion > MAX_DURACION_SEG:
            raise HTTPException(
                status_code=400,
                detail=f"El video dura {int(duracion // 60)} min y el maximo "
                f"es {MAX_DURACION_SEG // 60} min",
            )
    except Exception:
        if os.path.exists(origen):
            os.remove(origen)
        raise

    job = Job(
        id=session_uuid,
        user_id=current_user.id,
        project_id=project_id,
        source_filename=original_filename,
        video_type=video_type,
        duration_seconds=int(duracion) if duracion is not None else None,
    )
    ColaTrabajos(db).encolar(job)
    return TrabajoEncolado(job_id=job.id, status=job.status)


# --------------------------------------------------------------------- jobs


def _artefactos(job_id: str) -> dict:
    return {
        "video_karaoke": os.path.exists(_ruta_karaoke(job_id)),
        "video_instrumental": os.path.exists(_ruta_instrumental(job_id)),
        "audio_original": os.path.exists(os.path.join(DIR_AUDIOS, f"{job_id}.wav")),
        "audio_vocals": os.path.exists(
            os.path.join(DIR_AUDIOS, job_id, "vocals.wav")
        ),
        "audio_instrumental": os.path.exists(
            os.path.join(DIR_AUDIOS, job_id, "accompaniment.wav")
        ),
        "subtitulos_srt": os.path.exists(os.path.join(DIR_SRT, f"{job_id}.srt")),
        "subtitulos_ass": os.path.exists(os.path.join(DIR_ASS, f"{job_id}.ass")),
    }


def _job_propio(job_id: str, db: Session, user: User) -> Job:
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    if job.user_id != user.id:
        raise HTTPException(status_code=403, detail="No autorizado")
    return job


@router.get("/jobs", response_model=List[JobResponse])
def listar_jobs(
    project_id: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Historial de procesamientos del usuario."""
    q = db.query(Job).filter(Job.user_id == current_user.id)
    if project_id is not None:
        q = q.filter(Job.project_id == project_id)
    jobs = q.order_by(Job.created_at.desc()).limit(min(limit, 200)).all()

    return [_a_respuesta(j) for j in jobs]


def _a_respuesta(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        source_filename=job.source_filename,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        video_type=job.video_type,
        project_id=job.project_id,
        duration_seconds=job.duration_seconds,
        error=job.error,
        created_at=job.created_at,
        artifacts=_artefactos(job.id),
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def estado_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Detalle de un trabajo.

    Sirve tanto para seguir el progreso mientras el POST sigue en curso como
    para reabrir despues un procesamiento terminado desde el historial.
    """
    return _a_respuesta(_job_propio(job_id, db, current_user))


@router.delete("/jobs/{job_id}", status_code=204)
def borrar_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _job_propio(job_id, db, current_user)
    for m in db.query(Media).filter(Media.job_id == job_id).all():
        if m.path and os.path.exists(m.path):
            try:
                os.remove(m.path)
            except OSError:
                pass
        db.delete(m)
    carpeta = os.path.join(DIR_AUDIOS, job_id)
    if os.path.isdir(carpeta):
        shutil.rmtree(carpeta, ignore_errors=True)
    db.delete(job)
    db.commit()
    return



# --------------------------------------------------------------- forma de onda


def _calcular_picos(path: str, n: int = 180):
    """Extrae n picos normalizados de un WAV para dibujar la forma de onda.

    Se calcula en el servidor, donde ya esta el audio: el navegador solo recibe
    una lista pequena en lugar de descargar decenas de MB para analizarlos.
    """
    with wave.open(path, "rb") as w:
        canales = w.getnchannels()
        ancho = w.getsampwidth()
        total = w.getnframes()
        if total == 0 or ancho != 2:
            return []
        por_bloque = max(1, total // n)
        picos = []
        for _ in range(n):
            crudo = w.readframes(por_bloque)
            if not crudo:
                break
            muestras = array.array("h")
            muestras.frombytes(crudo[: len(crudo) - (len(crudo) % 2)])
            if canales > 1:
                muestras = muestras[::canales]
            picos.append(max((abs(x) for x in muestras), default=0) / 32768.0)

    if not picos:
        return []
    tope = max(picos) or 1.0
    return [round(min(1.0, p / tope), 4) for p in picos]


@router.get("/jobs/{job_id}/waveform/{tipo}")
def waveform(
    job_id: str,
    tipo: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Picos reales del audio, en cache junto al archivo."""
    if tipo not in ("audio_original", "audio_vocals", "audio_instrumental"):
        raise HTTPException(status_code=400, detail="Tipo de audio no valido")

    _job_propio(job_id, db, current_user)
    ruta = _ruta_de_tipo(tipo, job_id)
    if not ruta or not os.path.exists(ruta):
        raise HTTPException(status_code=404, detail="Audio no encontrado")

    cache = os.path.join(DIR_AUDIOS, job_id, f"{tipo}_peaks.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return {"peaks": json.load(f)}
        except Exception:
            pass

    try:
        picos = _calcular_picos(ruta)
    except Exception as e:
        print(f"[waveform] error: {e}")
        picos = []

    if picos:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        try:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(picos, f)
        except OSError:
            pass
    return {"peaks": picos}


# ----------------------------------------------------------------- descargas

_TIPOS = {
    "video_instrumental": ("video/mp4", "instrumental.mp4", "attachment"),
    "video_karaoke": ("video/mp4", "karaoke.mp4", "attachment"),
    "video_karaoke_preview": ("video/mp4", "karaoke_preview.mp4", "inline"),
    "subtitulos_srt": ("text/plain; charset=utf-8", "subtitulos.srt", "attachment"),
    "subtitulos_ass": ("text/plain; charset=utf-8", "karaoke.ass", "attachment"),
    "audio_original": ("audio/wav", "original.wav", "inline"),
    "audio_vocals": ("audio/wav", "vocals.wav", "inline"),
    "audio_instrumental": ("audio/wav", "instrumental.wav", "inline"),
}


def _ruta_de_tipo(tipo: str, job_id: str):
    return {
        "video_instrumental": _ruta_instrumental(job_id),
        "video_karaoke": _ruta_karaoke(job_id),
        "video_karaoke_preview": _ruta_karaoke(job_id),
        "subtitulos_srt": os.path.join(DIR_SRT, f"{job_id}.srt"),
        "subtitulos_ass": os.path.join(DIR_ASS, f"{job_id}.ass"),
        "audio_original": os.path.join(DIR_AUDIOS, f"{job_id}.wav"),
        "audio_vocals": os.path.join(DIR_AUDIOS, job_id, "vocals.wav"),
        "audio_instrumental": os.path.join(DIR_AUDIOS, job_id, "accompaniment.wav"),
    }.get(tipo)


@router.get("/descargar/todo/{job_id}")
def descargar_todo(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_media),
):
    """Empaqueta en un ZIP todo lo generado para el trabajo."""
    _job_propio(job_id, db, current_user)

    incluir = [
        ("video_karaoke", f"{job_id}_karaoke.mp4"),
        ("video_instrumental", f"{job_id}_instrumental.mp4"),
        ("audio_original", f"{job_id}_original.wav"),
        ("audio_vocals", f"{job_id}_vocals.wav"),
        ("audio_instrumental", f"{job_id}_instrumental.wav"),
        ("subtitulos_srt", f"{job_id}.srt"),
        ("subtitulos_ass", f"{job_id}.ass"),
    ]
    files_to_zip = []
    for tipo, nombre in incluir:
        ruta = _ruta_de_tipo(tipo, job_id)
        if ruta and os.path.exists(ruta):
            files_to_zip.append((ruta, nombre))

    if not files_to_zip:
        return JSONResponse(
            {"error": "No se encontraron archivos para descargar"}, status_code=404
        )

    fd, temp_zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path, filename in files_to_zip:
            zipf.write(file_path, filename)

    # El ZIP temporal se borra al terminar el envio (antes se acumulaban).
    return FileResponse(
        path=temp_zip_path,
        media_type="application/zip",
        filename=f"{job_id}_completo.zip",
        background=BackgroundTask(lambda: os.path.exists(temp_zip_path)
                                  and os.remove(temp_zip_path)),
    )


@router.get("/descargar/{tipo}/{job_id}")
def descargar_archivo(
    tipo: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_media),
):
    if tipo not in _TIPOS:
        return JSONResponse({"error": "Tipo de archivo no valido"}, status_code=400)

    _job_propio(job_id, db, current_user)

    media_type, sufijo, disposition = _TIPOS[tipo]
    file_path = _ruta_de_tipo(tipo, job_id)
    filename = f"{job_id}_{sufijo}"

    if not file_path or not os.path.exists(file_path):
        return JSONResponse(
            {"error": f"Archivo {tipo} no encontrado para job {job_id}"},
            status_code=404,
        )

    headers = {
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Accept-Ranges": "bytes",
    }
    if disposition == "inline":
        headers["Cache-Control"] = "no-cache"

    return FileResponse(
        path=file_path, media_type=media_type, filename=filename, headers=headers
    )
