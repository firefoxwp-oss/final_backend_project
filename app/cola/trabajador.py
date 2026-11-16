"""Trabajador de la cola de procesamiento.

Proceso independiente del servidor web que toma los trabajos en cola, uno a la
vez y por orden de llegada, y ejecuta el pipeline completo: extraccion del
audio, separacion de voces, video instrumental, transcripcion, subtitulos y
video karaoke.

Ejecucion: python -m app.cola.trabajador
"""

import os
import shutil
import signal
import subprocess
import time
import traceback

from app.archivos import (
    DIR_AUDIOS,
    DIR_ASS,
    DIR_PROYECTO,
    DIR_SRT,
    DIR_VIDEOS,
    crear_directorios,
    duracion_segundos,
    ejecutable_venv,
    ruta_instrumental,
    ruta_origen,
)
from app.cola.cola_trabajos import ColaTrabajos
from app.database import SessionLocal
from app.karaoke import generar_karaoke_desde_main, get_video_resolution
from app.models import Job
from app.subtitles import config_video_desde_resolucion, convertir_srt_a_ass

INTERVALO_SEG = float(os.getenv("TRABAJADOR_INTERVALO_SEG", "2"))


class Trabajador:
    def __init__(self, intervalo: float = INTERVALO_SEG):
        self.intervalo = intervalo
        self._detener = False

    def detener(self, *_):
        print("[trabajador] deteniendo...")
        self._detener = True

    def ejecutar(self) -> None:
        crear_directorios()
        print(f"[trabajador] esperando trabajos (cada {self.intervalo:g} s)")
        while not self._detener:
            try:
                if not self.procesar_siguiente():
                    time.sleep(self.intervalo)
            except Exception:
                # Un fallo de la base de datos no debe detener el servicio
                traceback.print_exc()
                time.sleep(self.intervalo)
        print("[trabajador] detenido")

    def procesar_siguiente(self) -> bool:
        """Procesa el siguiente trabajo en cola. Devuelve False si no habia ninguno."""
        with SessionLocal() as db:
            cola = ColaTrabajos(db)
            job = cola.siguiente()
            if job is None:
                db.rollback()
                return False
            cola.marcar_procesando(job)
            print(f"[trabajador] procesando {job.id} ({job.source_filename})")
            self.procesar(cola, job)
            return True

    def procesar(self, cola: ColaTrabajos, job: Job) -> None:
        job_id = job.id
        extension = os.path.splitext(job.source_filename)[1].lower()
        input_temp = ruta_origen(job_id, extension)
        output_dir = f"output_{job_id}"
        audio_file = os.path.join(DIR_AUDIOS, f"{job_id}.wav")
        video_sin_audio_file = os.path.join(DIR_VIDEOS, f"{job_id}_sin_audio.mp4")
        final_filename = ruta_instrumental(job_id)
        srt_path = os.path.join(DIR_SRT, f"{job_id}.srt")
        ass_path = os.path.join(DIR_ASS, f"{job_id}.ass")
        audio_permanent_dir = os.path.join(DIR_AUDIOS, job_id)
        permanent_instrumental = os.path.join(audio_permanent_dir, "accompaniment.wav")
        permanent_vocals = os.path.join(audio_permanent_dir, "vocals.wav")
        video_karaoke_path = None

        try:
            if not os.path.exists(input_temp):
                raise FileNotFoundError("No se encontro el archivo subido")

            if job.duration_seconds is None:
                duracion = duracion_segundos(input_temp)
                if duracion is not None:
                    job.duration_seconds = int(duracion)

            # 1) Audio y video sin audio
            cola.avanzar(job, "extrayendo_audio", 8)
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
            cola.registrar_archivo(job, audio_file, "wav", "audio")
            cola.registrar_archivo(job, video_sin_audio_file, "mp4", "video")

            # 2) Separacion de voces
            cola.avanzar(job, "separando_voces", 15)
            spleeter = os.getenv("SPLEETER_BIN") or ejecutable_venv("venv", "spleeter")
            subprocess.run(
                [spleeter, "separate", "-p", "spleeter:2stems", "-o", output_dir,
                 audio_file],
                check=True,
            )
            audio_basename = os.path.splitext(os.path.basename(audio_file))[0]
            instrumental_path = os.path.join(output_dir, audio_basename, "accompaniment.wav")
            vocals_path = os.path.join(output_dir, audio_basename, "vocals.wav")
            if not os.path.exists(instrumental_path):
                raise RuntimeError("Archivo instrumental no encontrado")

            os.makedirs(audio_permanent_dir, exist_ok=True)
            shutil.copy2(instrumental_path, permanent_instrumental)
            shutil.copy2(vocals_path, permanent_vocals)
            cola.registrar_archivo(job, permanent_instrumental, "wav", "audio_instrumental")
            cola.registrar_archivo(job, permanent_vocals, "wav", "audio_vocals")

            # 3) Video instrumental
            cola.avanzar(job, "generando_instrumental", 40)
            subprocess.run(
                ["ffmpeg", "-i", video_sin_audio_file, "-i", instrumental_path,
                 "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0",
                 final_filename, "-y"],
                check=True,
            )
            cola.registrar_archivo(job, final_filename, "mp4", "video_instrumental")

            # 4) Subtitulos y video karaoke, salvo que se pidiera solo el
            #    instrumental; si fallan, queda el instrumental
            if job.video_type != "instrumental":
                try:
                    video_karaoke_path = self.transcribir_y_generar_karaoke(
                        cola, job, vocals_path, audio_file, final_filename,
                        srt_path, ass_path,
                    )
                except Exception as e:
                    print(f"[job {job_id}] ERROR en subtitulos/karaoke: {e}")
                    traceback.print_exc()

            cola.marcar_terminado(
                job,
                [audio_file, permanent_instrumental, permanent_vocals, final_filename],
                "karaoke" if video_karaoke_path else "instrumental",
            )
            print(f"[trabajador] {job_id} terminado")

        except Exception as e:
            cola.db.rollback()
            print(f"[job {job_id}] ERROR: {e}")
            cola.marcar_error(job, str(e))

        finally:
            # Limpieza de intermedios
            for residuo in (input_temp, video_sin_audio_file):
                if os.path.exists(residuo):
                    try:
                        os.remove(residuo)
                    except OSError:
                        pass
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)

    def transcribir_y_generar_karaoke(self, cola, job, vocals_path, audio_file,
                                      final_filename, srt_path, ass_path):
        """Transcribe la voz, genera los subtitulos y compone el video karaoke."""
        cola.avanzar(job, "transcribiendo", 45)
        whisperx_py = os.getenv("WHISPERX_PY") or ejecutable_venv("venv_torch", "python")
        audio_in = vocals_path if os.path.exists(vocals_path) else audio_file
        script_path = os.path.join(DIR_PROYECTO, "app", "whisperx_run.py")
        resultado = subprocess.run(
            [whisperx_py, script_path, "--audio", audio_in, "--srt", srt_path],
            check=False,
            cwd=DIR_PROYECTO,
            capture_output=True,
            text=True,
        )
        if resultado.returncode != 0:
            print(resultado.stderr)
            raise RuntimeError("WhisperX fallo")
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"WhisperX no genero el SRT: {srt_path}")

        cola.avanzar(job, "generando_subtitulos", 78)
        resolucion = get_video_resolution(final_filename) or (1920, 1080)
        convertir_srt_a_ass(srt_path, ass_path,
                            cfg_video=config_video_desde_resolucion(*resolucion))
        cola.registrar_archivo(job, srt_path, "srt", "subtitle")
        cola.registrar_archivo(job, ass_path, "ass", "subtitle")

        if not os.path.exists(ass_path):
            return None
        cola.avanzar(job, "generando_karaoke", 85)
        resultado_karaoke = generar_karaoke_desde_main(job.id)
        if not resultado_karaoke["success"]:
            print(f"[job {job.id}] Error karaoke: {resultado_karaoke.get('error')}")
            return None
        video_karaoke_path = resultado_karaoke["video_karaoke_path"]
        cola.registrar_archivo(job, video_karaoke_path, "mp4", "video_karaoke")
        return video_karaoke_path


def main() -> None:
    trabajador = Trabajador()
    signal.signal(signal.SIGTERM, trabajador.detener)
    signal.signal(signal.SIGINT, trabajador.detener)
    trabajador.ejecutar()


if __name__ == "__main__":
    main()
