from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    Depends,
    HTTPException,
    status,
)
from typing import List, Optional
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from datetime import datetime, timezone
import subprocess
import os
import uuid
import shutil
import json
import zipfile
import tempfile
import wave
import array
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.migrate import aplicar_migraciones
from app.models import Base, Media, User, Project, Job
from app.schemas import (
    UserCreate,
    UserResponse,
    LoginRequest,
    Token,
    TokenRefresh,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    JobResponse,
)
from app.auth import (
    get_password_hash,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_current_user_media,
    get_db,
)
from app.subtitles import convertir_srt_a_ass, config_video_desde_resolucion
from app.karaoke import (
    karaoke_router,
    generar_karaoke_desde_main,
    get_video_resolution,
)

Base.metadata.create_all(bind=engine)
aplicar_migraciones(engine)

app = FastAPI()

# Origenes permitidos: configurables por entorno para poder desplegar.
_origins_env = os.getenv("FRONTEND_ORIGIN", "")
origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Job-ID",
        "X-Video-Type",
        "X-Archivos-Generados",
        "X-Karaoke-Error",
        "Content-Disposition",
    ],
)

app.include_router(karaoke_router)

# ----------------------------------------------------------------- constantes

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "1024")) * 1024 * 1024
MAX_DURACION_SEG = int(os.getenv("MAX_DURACION_MIN", "60")) * 60
EXTENSIONES_PERMITIDAS = {".mp4", ".avi", ".mkv", ".mp3", ".mov", ".m4v", ".webm"}

DIR_VIDEOS = os.path.join("media", "videos")
DIR_AUDIOS = os.path.join("media", "audios")
DIR_SRT = os.path.join("media", "subtitulos", "subtitulos_srt")
DIR_ASS = os.path.join("media", "subtitulos", "subtitulos_ass")


def _ruta_instrumental(job_id: str) -> str:
    return os.path.join(DIR_VIDEOS, f"{job_id}_sin_voces.mp4")


def _ruta_karaoke(job_id: str) -> str:
    return os.path.join(DIR_VIDEOS, f"{job_id}_karaoke.mp4")


def _registrar(db, job_id, user_id, project_id, path, formato, tipo):
    db.add(
        Media(
            name=os.path.basename(path),
            path=path,
            format=formato,
            type=tipo,
            job_id=job_id,
            user_id=user_id,
            project_id=project_id,
        )
    )


def _avanzar(db: Session, job: Job, stage: str, progress: int):
    """Publica el progreso real del pipeline para que el frontend lo consulte."""
    job.stage = stage
    job.progress = progress
    db.commit()
    print(f"[job {job.id}] {progress}% - {stage}")


def _duracion_segundos(path: str):
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path.replace("\\", "/"),
            ],
            text=True,
            timeout=30,
        )
        return float(out.strip())
    except Exception:
        return None


# --------------------------------------------------------------------- basico


@app.get("/")
def root():
    return {"message": "Backend running", "docs": "/docs", "redoc": "/redoc"}


@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )
    hashed_password = get_password_hash(user.password)
    db_user = User(name=user.name, email=user.email, password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, login_data.email, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "access_token": create_access_token(data={"sub": str(user.id)}),
        "refresh_token": create_refresh_token(data={"sub": str(user.id)}),
        "token_type": "bearer",
    }


@app.post("/refresh", response_model=Token)
def refresh_token(token_data: TokenRefresh):
    payload = decode_token(token_data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    return {
        "access_token": create_access_token(data={"sub": user_id}),
        "refresh_token": create_refresh_token(data={"sub": user_id}),
        "token_type": "bearer",
    }


@app.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ------------------------------------------------------------------- pipeline


# Nota: definido con `def` (no `async def`) a proposito. FastAPI ejecuta los
# endpoints sincronos en un threadpool, de modo que las llamadas bloqueantes a
# ffmpeg, Spleeter y WhisperX ya no congelan el event loop ni al resto de
# usuarios mientras se procesa un video.
@app.post("/procesar-video/")
def procesar_video(
    file: UploadFile = File(...),
    job_id: Optional[str] = Form(None),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    original_filename = file.filename or "video"
    base_name = os.path.splitext(original_filename)[0]
    base_name = "".join(
        c for c in base_name if c.isalnum() or c in (" ", "-", "_")
    ).strip() or "video"

    extension = os.path.splitext(original_filename)[1].lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no permitido ({extension}). Admitidos: "
            + ", ".join(sorted(EXTENSIONES_PERMITIDAS)),
        )

    if project_id is not None:
        proyecto = db.query(Project).filter(Project.id == project_id).first()
        if proyecto is None or proyecto.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Proyecto no autorizado")

    # El cliente puede proponer el id para poder consultar el progreso desde el
    # primer segundo, mientras esta peticion sigue en curso.
    session_uuid = job_id or str(uuid.uuid4())
    try:
        uuid.UUID(session_uuid)
    except ValueError:
        session_uuid = str(uuid.uuid4())
    if db.query(Job).filter(Job.id == session_uuid).first():
        session_uuid = str(uuid.uuid4())

    os.makedirs(DIR_VIDEOS, exist_ok=True)
    os.makedirs(DIR_AUDIOS, exist_ok=True)
    os.makedirs(DIR_SRT, exist_ok=True)
    os.makedirs(DIR_ASS, exist_ok=True)

    input_temp = os.path.join(DIR_VIDEOS, f"{session_uuid}_origen{extension}")
    output_dir = f"output_{session_uuid}"
    audio_file = os.path.join(DIR_AUDIOS, f"{session_uuid}.wav")
    video_sin_audio_file = os.path.join(DIR_VIDEOS, f"{session_uuid}_sin_audio.mp4")
    final_filename = _ruta_instrumental(session_uuid)

    job = Job(
        id=session_uuid,
        user_id=current_user.id,
        project_id=project_id,
        source_filename=original_filename,
        status="running",
        stage="recibiendo",
        progress=2,
    )
    db.add(job)
    db.commit()

    srt_path = os.path.join(DIR_SRT, f"{session_uuid}.srt")
    ass_path = os.path.join(DIR_ASS, f"{session_uuid}.ass")
    video_karaoke_path = None

    try:
        # 1) Guardado por bloques: antes se cargaba el archivo entero en RAM.
        escrito = 0
        with open(input_temp, "wb") as f:
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

        duracion = _duracion_segundos(input_temp)
        if duracion is not None:
            job.duration_seconds = int(duracion)
            if duracion > MAX_DURACION_SEG:
                raise HTTPException(
                    status_code=400,
                    detail=f"El video dura {int(duracion // 60)} min y el maximo "
                    f"es {MAX_DURACION_SEG // 60} min",
                )

        _avanzar(db, job, "extrayendo_audio", 8)
        subprocess.run(
            ["ffmpeg", "-i", input_temp, "-vn", "-ac", "2", "-ar", "44100",
             audio_file, "-y"],
            check=True,
        )

        subprocess.run(
            ["ffmpeg", "-i", input_temp, "-c", "copy", "-an",
             video_sin_audio_file, "-y"],
            check=True,
        )

        _registrar(db, session_uuid, current_user.id, project_id,
                   audio_file, "wav", "audio")
        _registrar(db, session_uuid, current_user.id, project_id,
                   video_sin_audio_file, "mp4", "video")
        db.commit()

        # 2) Separacion de voces
        _avanzar(db, job, "separando_voces", 15)
        project_root = os.path.dirname(os.path.dirname(__file__))
        spleeter_executable = os.path.join(
            project_root, "venv", "Scripts", "spleeter.exe"
        )
        subprocess.run(
            [spleeter_executable, "separate", "-p", "spleeter:2stems",
             "-o", output_dir, audio_file],
            check=True,
        )
        print("Etapa: Separacion de stems completada (Spleeter).")

        audio_basename = os.path.splitext(os.path.basename(audio_file))[0]
        instrumental_path = os.path.join(output_dir, audio_basename, "accompaniment.wav")
        vocals_path = os.path.join(output_dir, audio_basename, "vocals.wav")

        if not os.path.exists(instrumental_path):
            raise RuntimeError("Archivo instrumental no encontrado")

        audio_permanent_dir = os.path.join(DIR_AUDIOS, session_uuid)
        os.makedirs(audio_permanent_dir, exist_ok=True)
        permanent_instrumental = os.path.join(audio_permanent_dir, "accompaniment.wav")
        permanent_vocals = os.path.join(audio_permanent_dir, "vocals.wav")
        shutil.copy2(instrumental_path, permanent_instrumental)
        shutil.copy2(vocals_path, permanent_vocals)
        _registrar(db, session_uuid, current_user.id, project_id,
                   permanent_instrumental, "wav", "audio_instrumental")
        _registrar(db, session_uuid, current_user.id, project_id,
                   permanent_vocals, "wav", "audio_vocals")
        db.commit()

        # 3) Video instrumental
        _avanzar(db, job, "generando_instrumental", 40)
        subprocess.run(
            ["ffmpeg", "-i", video_sin_audio_file, "-i", instrumental_path,
             "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0",
             final_filename, "-y"],
            check=True,
        )
        _registrar(db, session_uuid, current_user.id, project_id,
                   final_filename, "mp4", "video_instrumental")
        db.commit()

        # 4) Subtitulos
        try:
            _avanzar(db, job, "transcribiendo", 45)
            venv_torch_python = os.getenv(
                "WHISPERX_PY",
                os.path.join(project_root, "venv_torch", "Scripts", "python.exe"),
            )
            audio_in = vocals_path if os.path.exists(vocals_path) else audio_file
            project_root_abs = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..")
            )
            script_path = os.path.join(project_root_abs, "app", "whisperx_run.py")

            resultado_whisperx = subprocess.run(
                [venv_torch_python, script_path, "--audio", audio_in,
                 "--srt", srt_path],
                check=False,
                cwd=project_root_abs,
                capture_output=True,
                text=True,
            )
            if resultado_whisperx.returncode != 0:
                print(f"ERROR WhisperX ({resultado_whisperx.returncode})")
                print(resultado_whisperx.stderr)
                raise RuntimeError("WhisperX fallo")
            if not os.path.exists(srt_path):
                raise FileNotFoundError(f"WhisperX no genero el SRT: {srt_path}")

            print("Etapa: Transcripcion completada (WhisperX).")
            _avanzar(db, job, "generando_subtitulos", 78)

            # El ASS se genera a la resolucion real del video, de modo que ya no
            # hace falta reescalar el video a 1080p antes de quemarlo.
            resolucion = get_video_resolution(final_filename) or (1920, 1080)
            cfg_video = config_video_desde_resolucion(*resolucion)
            convertir_srt_a_ass(srt_path, ass_path, cfg_video=cfg_video)
            print(f"Conversion SRT->ASS completada ({resolucion[0]}x{resolucion[1]})")

            _registrar(db, session_uuid, current_user.id, project_id,
                       srt_path, "srt", "subtitle")
            _registrar(db, session_uuid, current_user.id, project_id,
                       ass_path, "ass", "subtitle")
            db.commit()

            if os.path.exists(ass_path):
                _avanzar(db, job, "generando_karaoke", 85)
                resultado_karaoke = generar_karaoke_desde_main(session_uuid)
                if resultado_karaoke["success"]:
                    video_karaoke_path = resultado_karaoke["video_karaoke_path"]
                    _registrar(db, session_uuid, current_user.id, project_id,
                               video_karaoke_path, "mp4", "video_karaoke")
                    db.commit()
                    print(f"Video karaoke generado: {video_karaoke_path}")
                else:
                    print(f"Error karaoke: {resultado_karaoke.get('error')}")

        except Exception as e:
            print(f"ERROR en subtitulos/karaoke: {e}")
            import traceback

            traceback.print_exc()

        job.video_type = "karaoke" if video_karaoke_path else "instrumental"
        job.status = "done"
        job.stage = "completado"
        job.progress = 100
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

        archivos = {
            "video_instrumental": final_filename,
            "subtitulos_srt": srt_path if os.path.exists(srt_path) else None,
            "subtitulos_ass": ass_path if os.path.exists(ass_path) else None,
            "video_karaoke": video_karaoke_path,
        }

        if video_karaoke_path and os.path.exists(video_karaoke_path):
            return FileResponse(
                path=video_karaoke_path,
                media_type="video/mp4",
                filename=f"{base_name}_karaoke.mp4",
                headers={
                    "X-Job-ID": session_uuid,
                    "X-Video-Type": "karaoke",
                    "X-Archivos-Generados": json.dumps(archivos),
                },
            )
        return FileResponse(
            path=final_filename,
            media_type="video/mp4",
            filename=f"{base_name}_instrumental.mp4",
            headers={
                "X-Job-ID": session_uuid,
                "X-Video-Type": "instrumental",
                "X-Archivos-Generados": json.dumps(archivos),
                "X-Karaoke-Error": "Video karaoke no generado",
            },
        )

    except HTTPException as e:
        db.rollback()
        job.status = "error"
        job.error = str(e.detail)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise

    except Exception as e:
        db.rollback()
        job.status = "error"
        job.error = str(e)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return JSONResponse(
            {"error": f"Error procesando el video: {str(e)}"}, status_code=500
        )

    finally:
        # Limpieza de intermedios: antes quedaban en disco indefinidamente.
        for residuo in (input_temp, video_sin_audio_file):
            if os.path.exists(residuo):
                try:
                    os.remove(residuo)
                except OSError:
                    pass
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir, ignore_errors=True)


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


@app.get("/jobs", response_model=List[JobResponse])
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


@app.get("/jobs/{job_id}", response_model=JobResponse)
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


@app.delete("/jobs/{job_id}", status_code=204)
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


@app.get("/jobs/{job_id}/waveform/{tipo}")
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


@app.get("/descargar/todo/{job_id}")
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


@app.get("/descargar/{tipo}/{job_id}")
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


# ------------------------------------------------------------------ proyectos


@app.get("/projects", response_model=List[ProjectResponse])
def get_projects(
    userId: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if userId is not None and current_user.id != userId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    return (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )


@app.post("/projects", response_model=ProjectResponse)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    project = Project(
        name=payload.name, description=payload.description, user_id=payload.user_id
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.put("/projects/{id}", response_model=ProjectResponse)
def update_project(
    id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        project.description = payload.description
    db.commit()
    db.refresh(project)
    return project


@app.delete("/projects/{id}", status_code=204)
def delete_project(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == id).first()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado"
        )
    if project.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado"
        )
    db.query(Job).filter(Job.project_id == id).update({Job.project_id: None})
    db.query(Media).filter(Media.project_id == id).update({Media.project_id: None})
    db.delete(project)
    db.commit()
    return
