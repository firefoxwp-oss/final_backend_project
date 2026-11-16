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

from app.cola.cola_trabajos import ColaTrabajos
from app.karaoke.karaoke import generar_karaoke_desde_main, get_video_resolution
from app.persistencia.archivos import (
    DIR_AUDIOS,
    DIR_ASS,
    DIR_SRT,
    DIR_VIDEOS,
    crear_directorios,
    duracion_segundos,
    ruta_instrumental,
    ruta_origen,
)
from app.persistencia.database import SessionLocal
from app.persistencia.models import Job
from app.separacion.separador_spleeter import SeparadorSpleeter
from app.separacion.separador_voz import SeparadorVoz
from app.subtitulos.subtitles import config_video_desde_resolucion, convertir_srt_a_ass
from app.transcripcion.transcriptor import transcribir

INTERVALO_SEG = float(os.getenv("TRABAJADOR_INTERVALO_SEG", "2"))


class Trabajador:
    def __init__(self, separador: SeparadorVoz = None, intervalo: float = INTERVALO_SEG):
        self.separador = separador or SeparadorSpleeter()
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
        audio_permanent_dir = os.path.join(DIR_AUDIOS, job_id)
        permanent_instrumental = os.path.join(audio_permanent_dir, "accompaniment.wav")
        permanent_vocals = os.path.join(audio_permanent_dir, "vocals.wav")

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
            separacion = self.separador.separar(audio_file, output_dir)
            os.makedirs(audio_permanent_dir, exist_ok=True)
            shutil.copy2(separacion.instrumental, permanent_instrumental)
            shutil.copy2(separacion.voz, permanent_vocals)
            cola.registrar_archivo(job, permanent_instrumental, "wav", "audio_instrumental")
            cola.registrar_archivo(job, permanent_vocals, "wav", "audio_vocals")

            # 3) Video instrumental
            cola.avanzar(job, "generando_instrumental", 40)
            subprocess.run(
                ["ffmpeg", "-i", video_sin_audio_file, "-i", separacion.instrumental,
                 "-c:v", "copy", "-map", "0:v:0", "-map", "1:a:0",
                 final_filename, "-y"],
                check=True,
            )
            cola.registrar_archivo(job, final_filename, "mp4", "video_instrumental")

            # 4) Subtitulos y video karaoke: si fallan, queda el instrumental
            video_karaoke_path = None
            try:
                video_karaoke_path = self.transcribir_y_generar_karaoke(
                    cola, job, permanent_vocals, final_filename
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

    def transcribir_y_generar_karaoke(self, cola: ColaTrabajos, job: Job, voz: str,
                                      video_instrumental: str):
        """Transcribe la voz, genera los subtitulos y compone el video karaoke."""
        srt_path = os.path.join(DIR_SRT, f"{job.id}.srt")
        ass_path = os.path.join(DIR_ASS, f"{job.id}.ass")

        cola.avanzar(job, "transcribiendo", 45)
        transcribir(voz, srt_path)

        cola.avanzar(job, "generando_subtitulos", 78)
        resolucion = get_video_resolution(video_instrumental) or (1920, 1080)
        convertir_srt_a_ass(srt_path, ass_path,
                            cfg_video=config_video_desde_resolucion(*resolucion))
        cola.registrar_archivo(job, srt_path, "srt", "subtitle")
        cola.registrar_archivo(job, ass_path, "ass", "subtitle")

        if not os.path.exists(ass_path):
            return None
        cola.avanzar(job, "generando_karaoke", 85)
        resultado = generar_karaoke_desde_main(job.id)
        if not resultado["success"]:
            print(f"[job {job.id}] Error karaoke: {resultado.get('error')}")
            return None
        cola.registrar_archivo(job, resultado["video_karaoke_path"], "mp4", "video_karaoke")
        return resultado["video_karaoke_path"]


def main() -> None:
    trabajador = Trabajador()
    signal.signal(signal.SIGTERM, trabajador.detener)
    signal.signal(signal.SIGINT, trabajador.detener)
    trabajador.ejecutar()


if __name__ == "__main__":
    main()
