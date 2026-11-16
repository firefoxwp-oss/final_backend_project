"""
Módulo Karaoke: Sistema optimizado de generación de video karaoke
Usa archivos ya procesados del proyecto principal
Integrado como servicio en el backend principal
"""

import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_current_user_media, get_db
from app.models import Job, User

# Cargar variables de entorno
load_dotenv()

# Configuración Karaoke optimizada - usar estructura del proyecto principal
KARAOKE_PRESET_X264 = os.getenv("KARAOKE_PRESET_X264", "veryfast")
KARAOKE_CRF = int(os.getenv("KARAOKE_CRF", "20"))

# Timeouts para FFmpeg (en segundos)
FFMPEG_TIMEOUT_COMPOSICION = 1800  # 30 minutos para composición final

# Crear router para el servicio Karaoke
karaoke_router = APIRouter(prefix="/karaoke", tags=["karaoke"])

# Estados de jobs en memoria (en producción usar Redis/DB)
estados_jobs = {}


def verificar_propiedad(job_id: str, db: Session, user: User) -> Job:
    """Un usuario solo puede operar sobre sus propios trabajos."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "404_JOB_NO_ENCONTRADO",
                "mensaje": "Trabajo no encontrado",
            },
        )
    if job.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail={"codigo": "403_NO_AUTORIZADO", "mensaje": "No autorizado"},
        )
    return job


# Función utilitaria para ser llamada desde main.py
def generar_karaoke_desde_main(job_id: str) -> Dict[str, Any]:
    """
    Función para ser llamada desde main.py después del procesamiento principal.
    Genera el video karaoke de forma síncrona y retorna el resultado.
    """
    try:
        rutas = resolver_rutas_karaoke(job_id)

        # Validar que existan los archivos necesarios
        info_archivos = validar_archivos_entrada_karaoke(rutas)

        # Generar video karaoke
        video_karaoke = componer_video_karaoke(rutas)

        return {
            "success": True,
            "video_karaoke_path": str(video_karaoke),
            "job_id": job_id,
            "archivos_origen": info_archivos,
        }

    except HTTPException as e:
        error_msg = (
            e.detail.get("mensaje", str(e.detail))
            if isinstance(e.detail, dict)
            else str(e.detail)
        )
        return {"success": False, "error": error_msg, "job_id": job_id}
    except Exception as e:
        return {
            "success": False,
            "error": f"Error interno: {str(e)}",
            "job_id": job_id,
        }


# Modelos Pydantic para respuestas
class RespuestaEjecutar(BaseModel):
    """Respuesta del endpoint ejecutar"""

    job_id: str
    status: str  # "queued", "done", "processing", "error"
    mensaje: Optional[str] = None


class RespuestaEstado(BaseModel):
    """Respuesta del endpoint estado"""

    status: str
    progreso: Optional[int] = Field(None, ge=0, le=100)
    mensaje: Optional[str] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


def buscar_archivo_ass_inteligente(job_id: str) -> Path:
    """Busca archivo ASS con múltiples formatos posibles"""
    base_path = Path("media") / "subtitulos" / "subtitulos_ass"

    # Formatos posibles que puede generar main.py
    formatos_posibles = [
        f"{job_id}.ass",  # Formato directo
        f"{job_id}_sin_voces.ass",  # Formato que genera main.py
    ]

    for formato in formatos_posibles:
        ruta_candidata = base_path / formato
        if ruta_candidata.exists():
            return ruta_candidata

    # Si no existe ninguno, devolver el formato preferido (para el error)
    return base_path / f"{job_id}.ass"


def resolver_rutas_karaoke(job_id: str) -> Dict[str, Path]:
    """Resuelve las rutas del proyecto principal para el servicio karaoke"""

    # Rutas del proyecto principal con búsqueda inteligente
    rutas = {
        # Video instrumental final del proyecto principal (raíz del proyecto)
        "ruta_video_instrumental": Path("media")
        / "videos"
        / f"{job_id}_sin_voces.mp4",
        # Subtítulos ASS del proyecto principal (búsqueda inteligente)
        "ruta_subtitulos_ass": buscar_archivo_ass_inteligente(job_id),
        # Salida del video karaoke final
        "ruta_video_karaoke": Path("media")
        / "videos"
        / f"{job_id}_karaoke.mp4",
        # Metadatos para tracking de karaoke
        "dir_metadatos": Path("media") / "metadatos" / "karaoke" / job_id,
        "archivo_estado": Path("media")
        / "metadatos"
        / "karaoke"
        / job_id
        / "estado.json",
        "archivo_log": Path("media")
        / "metadatos"
        / "karaoke"
        / job_id
        / "ffmpeg.log",
    }

    return rutas


def asegurar_carpetas(*rutas):
    """Crea las carpetas si no existen"""
    for ruta in rutas:
        Path(ruta).mkdir(parents=True, exist_ok=True)


def get_video_resolution(path: Path):
    """Devuelve (width, height) del primer stream de video usando ffprobe."""
    try:
        # Convertir ruta a forward slashes para ffprobe en Windows
        path_str = str(path).replace("\\", "/")

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            path_str,
        ]
        out = subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT, timeout=10
        )
        out = out.strip()
        if not out:
            return None
        parts = out.split("x")
        if len(parts) != 2:
            return None
        return int(parts[0]), int(parts[1])
    except Exception as e:
        print(f"Warning: No se pudo obtener resolución de {path}: {e}")
        return None


def validar_archivos_entrada_karaoke(rutas: Dict[str, Path]) -> Dict[str, Any]:
    """Valida que existan los archivos necesarios para el karaoke"""
    ruta_video = rutas["ruta_video_instrumental"]
    ruta_ass = rutas["ruta_subtitulos_ass"]

    if not ruta_video.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "404_VIDEO_NO_ENCONTRADO",
                "mensaje": f"No se encontró video instrumental: {ruta_video}",
            },
        )

    if not ruta_ass.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "codigo": "404_ASS_NO_ENCONTRADO",
                "mensaje": f"No se encontraron subtítulos ASS: {ruta_ass}",
            },
        )

    # Verificar tamaño del video
    tamaño_mb = ruta_video.stat().st_size / (1024 * 1024)

    return {
        "video_instrumental": str(ruta_video),
        "subtitulos_ass": str(ruta_ass),
        "tamaño_mb": tamaño_mb,
    }


def componer_video_karaoke(rutas: Dict[str, Path]) -> Path:
    """Compone el video karaoke con el video instrumental + subtítulos ASS"""
    ruta_video_instrumental = rutas["ruta_video_instrumental"]
    ruta_subtitulos_ass = rutas["ruta_subtitulos_ass"]
    ruta_output = rutas["ruta_video_karaoke"]
    ruta_log = rutas["archivo_log"]

    asegurar_carpetas(ruta_output.parent)

    # El video se usa en su resolucion nativa. El ASS se genera con
    # PlayResX/PlayResY iguales a esa resolucion, asi que no hace falta
    # reescalar: se ahorra un reencode completo por trabajo.
    ruta_video_actual = ruta_video_instrumental
    actualizar_estado_karaoke(
        rutas,
        "preparando_composicion",
        70,
        "Video preparado para composicion (resolucion nativa)",
    )

    # Comando FFmpeg optimizado - usar video (posiblemente redimensionado)
    # Para Windows, convertir rutas a forward slashes para ffmpeg
    # FFmpeg en Windows entiende forward slashes mejor que escaped backslashes
    ruta_video_str = str(ruta_video_actual).replace("\\", "/")
    ruta_subs_str = str(ruta_subtitulos_ass).replace("\\", "/")
    ruta_output_str = str(ruta_output).replace("\\", "/")

    # Escapar caracteres especiales en la ruta del filtro subtitles
    # En Windows, los dos puntos de las rutas (C:) necesitan escaparse
    ruta_subs_escaped = ruta_subs_str.replace(":", r"\:")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        ruta_video_str,  # Video instrumental (ya tiene audio)
        "-vf",
        f"subtitles={ruta_subs_escaped}",  # Agregar subtítulos ASS
        "-c:v",
        "libx264",
        "-preset",
        KARAOKE_PRESET_X264,
        "-crf",
        str(KARAOKE_CRF),
        "-c:a",
        "copy",  # Mantener audio sin recodificar
        ruta_output_str,
    ]

    try:
        asegurar_carpetas(ruta_log.parent)

        print("Incrustando subtítulos ASS con ffmpeg...")
        with open(ruta_log, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"=== Composición final karaoke - {datetime.now()} ===\n"
            )
            log_file.write(
                f"Video instrumental (usado): {ruta_video_actual}\n"
            )
            log_file.write(f"Subtítulos ASS: {ruta_subtitulos_ass}\n")
            log_file.write(f"Output: {ruta_output}\n")
            log_file.write(f"Comando: {' '.join(cmd)}\n\n")

            # Ejecutar FFmpeg con timeout
            actualizar_estado_karaoke(
                rutas,
                "componiendo",
                85,
                "Incrustando subtítulos y codificando video karaoke",
            )
            subprocess.run(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
                timeout=FFMPEG_TIMEOUT_COMPOSICION,
            )

        if not ruta_output.exists():
            raise subprocess.CalledProcessError(
                1, cmd, "Video karaoke no generado"
            )

        # Actualizar estado final
        actualizar_estado_karaoke(
            rutas, "done", 100, "Video karaoke generado exitosamente"
        )
        return ruta_output

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_FFMPEG_TIMEOUT",
                "mensaje": (
                    "Timeout en composición: proceso excedió "
                    f"{FFMPEG_TIMEOUT_COMPOSICION} segundos"
                ),
            },
        )
    except subprocess.CalledProcessError as e:
        # Leer el log para obtener más información del error
        error_details = f"FFmpeg falló con código {e.returncode}"
        if ruta_log.exists():
            try:
                with open(ruta_log, "r", encoding="utf-8") as f:
                    log_content = f.read()
                    error_details += f". Log: {log_content[-500:]}"
            except Exception:
                pass

        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_FFMPEG_ERROR",
                "mensaje": (
                    f"Error en composición de video karaoke: {error_details}"
                ),
            },
        )


def actualizar_estado_karaoke(
    rutas: Dict[str, Path], estado: str, progreso: int = 0, mensaje: str = None
):
    """Actualiza el estado del job karaoke en el archivo JSON"""
    asegurar_carpetas(rutas["dir_metadatos"])

    info_estado = {
        "status": estado,
        "progreso": progreso,
        "timestamp": datetime.now().isoformat(),
        "mensaje": mensaje,
    }

    # Mantener error si existe
    archivo_estado = rutas["archivo_estado"]
    if archivo_estado.exists():
        try:
            with open(archivo_estado, "r", encoding="utf-8") as f:
                estado_previo = json.load(f)
                if estado_previo.get("error"):
                    info_estado["error"] = estado_previo["error"]
        except Exception:
            pass

    with open(archivo_estado, "w", encoding="utf-8") as f:
        json.dump(info_estado, f, ensure_ascii=False, indent=2)

    # También actualizar en memoria
    job_id_from_path = str(archivo_estado.parent.name)
    estados_jobs[job_id_from_path] = info_estado


def ejecutar_pipeline_karaoke(job_id: str):
    """Ejecuta el pipeline de generación de video karaoke"""
    try:
        rutas = resolver_rutas_karaoke(job_id)

        # 1. Validar archivos de entrada del proyecto principal
        actualizar_estado_karaoke(
            rutas,
            "validando_archivos",
            20,
            "Validando archivos del proyecto principal",
        )

        validar_archivos_entrada_karaoke(rutas)

        # 2. Componer video karaoke directamente
        actualizar_estado_karaoke(
            rutas, "generando_video", 50, "Componiendo video karaoke"
        )

        componer_video_karaoke(rutas)

        # 3. Finalizar
        actualizar_estado_karaoke(
            rutas, "done", 100, "Video karaoke generado exitosamente"
        )

    except HTTPException as e:
        # Extraer el mensaje si el detalle es un dict, si no usar el detalle
        if isinstance(e.detail, dict):
            mensaje_error = e.detail.get("mensaje", str(e.detail))
        else:
            mensaje_error = str(e.detail)
        actualizar_estado_error_karaoke(rutas, mensaje_error)
    except Exception as e:
        actualizar_estado_error_karaoke(rutas, f"Error interno: {str(e)}")


def actualizar_estado_error_karaoke(
    rutas: Dict[str, Path], mensaje_error: str
):
    """Actualiza el estado a error con mensaje"""
    try:
        asegurar_carpetas(rutas["dir_metadatos"])

        info_estado = {
            "status": "error",
            "progreso": 0,
            "timestamp": datetime.now().isoformat(),
            "error": mensaje_error,
            "mensaje": "Error durante el procesamiento",
        }

        with open(rutas["archivo_estado"], "w", encoding="utf-8") as f:
            json.dump(info_estado, f, ensure_ascii=False, indent=2)

        # También actualizar en memoria
        job_id_from_path = str(rutas["archivo_estado"].parent.name)
        estados_jobs[job_id_from_path] = info_estado

    except Exception as e_interno:
        print(f"Error actualizando estado de error: {e_interno}")


def leer_estado_job_karaoke(rutas: Dict[str, Path]) -> Dict[str, Any]:
    """Lee el estado actual del job desde archivo o memoria"""
    archivo_estado = rutas["archivo_estado"]

    # Primero intentar leer desde archivo
    if archivo_estado.exists():
        try:
            with open(archivo_estado, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fallback: buscar en memoria
    job_id_from_path = str(archivo_estado.parent.name)
    if job_id_from_path in estados_jobs:
        return estados_jobs[job_id_from_path]

    # Estado por defecto
    return {
        "status": "not_found",
        "progreso": 0,
        "timestamp": datetime.now().isoformat(),
        "mensaje": "Job no encontrado",
    }


# Endpoints principales del servicio Karaoke
@karaoke_router.post("/ejecutar/{job_id}", response_model=RespuestaEjecutar)
async def ejecutar_karaoke(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Endpoint karaoke: usa archivos ya generados por el proyecto principal
    """
    verificar_propiedad(job_id, db, current_user)
    try:
        # 1. Resolver rutas usando la estructura del proyecto principal
        rutas = resolver_rutas_karaoke(job_id)

        # 2. Verificar si ya existe el video karaoke (idempotencia)
        if rutas["ruta_video_karaoke"].exists():
            return RespuestaEjecutar(
                job_id=job_id,
                status="done",
                mensaje="Video karaoke ya generado previamente",
            )

        # 3. Verificar estado actual
        estado_actual = leer_estado_job_karaoke(rutas)
        if estado_actual.get("status") in [
            "processing",
            "validando_archivos",
            "generando_video",
        ]:
            return RespuestaEjecutar(
                job_id=job_id,
                status="processing",
                mensaje="Job ya en procesamiento",
            )

        # 4. Iniciar procesamiento asíncrono
        actualizar_estado_karaoke(
            rutas, "queued", 0, "Job encolado para procesamiento"
        )

        # Ejecutar en hilo separado para no bloquear FastAPI
        hilo_procesamiento = threading.Thread(
            target=ejecutar_pipeline_karaoke, args=(job_id,), daemon=True
        )
        hilo_procesamiento.start()

        return RespuestaEjecutar(
            job_id=job_id, status="queued", mensaje="Procesamiento iniciado"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_ERROR_INTERNO",
                "mensaje": f"Error interno: {str(e)}",
            },
        )


@karaoke_router.get("/estado/{job_id}", response_model=RespuestaEstado)
async def consultar_estado_karaoke(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Consulta el estado de un job karaoke específico
    """
    verificar_propiedad(job_id, db, current_user)
    try:
        rutas = resolver_rutas_karaoke(job_id)
        estado = leer_estado_job_karaoke(rutas)

        return RespuestaEstado(
            status=estado.get("status", "not_found"),
            progreso=estado.get("progreso", 0),
            mensaje=estado.get("mensaje"),
            timestamp=estado.get("timestamp"),
            error=estado.get("error"),
        )

    except Exception as e:
        return RespuestaEstado(
            status="error", mensaje=f"Error consultando estado: {str(e)}"
        )


@karaoke_router.get("/descargar/{job_id}")
async def descargar_video_karaoke(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_media),
):
    """
    Sirve el video karaoke MP4 generado para descarga
    """
    verificar_propiedad(job_id, db, current_user)
    try:
        rutas = resolver_rutas_karaoke(job_id)
        ruta_video = rutas["ruta_video_karaoke"]

        if not ruta_video.exists():
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": "404_VIDEO_NO_ENCONTRADO",
                    "mensaje": (
                        f"Video karaoke no encontrado para job {job_id}"
                    ),
                },
            )

        # Verificar que el archivo es accesible
        try:
            tamaño = ruta_video.stat().st_size
            if tamaño == 0:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "codigo": "404_VIDEO_VACIO",
                        "mensaje": "El video existe pero está vacío",
                    },
                )
        except OSError:
            raise HTTPException(
                status_code=500,
                detail={
                    "codigo": "500_VIDEO_INACCESIBLE",
                    "mensaje": "No se puede acceder al archivo de video",
                },
            )

        return FileResponse(
            path=str(ruta_video),
            filename=f"karaoke_{job_id}.mp4",
            media_type="video/mp4",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=karaoke_{job_id}.mp4"
                )
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_ERROR_DESCARGA",
                "mensaje": f"Error en descarga: {str(e)}",
            },
        )


@karaoke_router.get("/preview/{job_id}")
async def preview_video_karaoke(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_media),
):
    """
    Sirve el video karaoke para previsualización en el navegador.
    """
    verificar_propiedad(job_id, db, current_user)
    try:
        rutas = resolver_rutas_karaoke(job_id)
        ruta_video = rutas["ruta_video_karaoke"]

        print("========== PREVIEW KARAOKE ==========")
        print("JOB ID:", job_id)
        print("RUTA:", ruta_video)
        print("RUTA ABSOLUTA:", ruta_video.resolve())
        print("EXISTE:", ruta_video.exists())

        if ruta_video.exists():
            print("TAMAÑO:", ruta_video.stat().st_size, "bytes")

        print("======================================")

        if not ruta_video.exists():
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": "404_VIDEO_NO_ENCONTRADO",
                    "mensaje": (
                        f"Video karaoke no encontrado para job {job_id}"
                    ),
                },
            )

        tamaño = ruta_video.stat().st_size

        if tamaño == 0:
            raise HTTPException(
                status_code=404,
                detail={
                    "codigo": "404_VIDEO_VACIO",
                    "mensaje": "El video existe pero está vacío",
                },
            )

        return FileResponse(
            path=str(ruta_video),
            media_type="video/mp4",
            filename=f"karaoke_{job_id}_preview.mp4",
            headers={
                "Content-Disposition": (
                    f'inline; filename="karaoke_{job_id}_preview.mp4"'
                ),
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache",
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        import traceback

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail={
                "codigo": "500_ERROR_PREVIEW",
                "mensaje": f"Error en preview: {str(e)}",
            },
        )


@karaoke_router.get("/info")
async def info_karaoke():
    """
    Información del servicio Karaoke
    """
    return {
        "servicio": "Servicio Video Karaoke",
        "version": "1.0.0",
        "descripcion": (
            "Sistema integrado que usa archivos del proyecto principal"
        ),
        "endpoints": {
            "ejecutar": "POST /karaoke/ejecutar/{job_id}",
            "estado": "GET /karaoke/estado/{job_id}",
            "preview": "GET /karaoke/preview/{job_id}",
            "descargar": "GET /karaoke/descargar/{job_id}",
            "info": "GET /karaoke/info",
            "health": "GET /karaoke/health",
        },
        "archivos_necesarios": {
            "video_instrumental": "{job_id}_sin_voces.mp4 (raíz del proyecto)",
            "subtitulos_ass": "media/subtitulos/subtitulos_ass/{job_id}.ass",
        },
        "salida": {"video_karaoke": "media/videos/{job_id}_karaoke.mp4"},
        "configuracion": {
            "preset_x264": KARAOKE_PRESET_X264,
            "crf": KARAOKE_CRF,
        },
    }


# Health check del servicio karaoke
@karaoke_router.get("/health")
async def health_check_karaoke():
    """Health check del servicio karaoke"""
    try:
        # Verificar FFmpeg
        ffmpeg_ok = False
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            ffmpeg_ok = True
        except Exception:
            pass

        # Verificar estructura de directorios del proyecto principal
        dirs_ok = all(
            [
                Path("media").exists(),
                Path("media/videos").exists(),
                Path("media/subtitulos").exists(),
                Path("media/subtitulos/subtitulos_ass").exists(),
            ]
        )

        # Verificar permisos de escritura
        write_ok = False
        try:
            test_file = Path("media/test_write.tmp")
            test_file.write_text("test")
            test_file.unlink()
            write_ok = True
        except Exception:
            pass

        status = (
            "healthy" if (ffmpeg_ok and dirs_ok and write_ok) else "unhealthy"
        )

        return {
            "status": status,
            "checks": {
                "ffmpeg_disponible": ffmpeg_ok,
                "directorios_proyecto_ok": dirs_ok,
                "permisos_escritura": write_ok,
            },
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }
