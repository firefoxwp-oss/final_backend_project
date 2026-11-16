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
import tempfile
import time
import traceback

from app.archivos import (
    DIR_AUDIOS,
    DIR_ASS,
    DIR_PROYECTO,
    DIR_SRT,
    DIR_VIDEOS,
    archivos_del_trabajo,
    crear_directorios,
    duracion_segundos,
    ejecutable_venv,
    eliminar_rutas,
    ruta_instrumental,
    ruta_letra,
    ruta_origen,
    ruta_pista_comprimida,
)
from app.cola.cola_trabajos import ColaTrabajos, TrabajoCancelado
from app.database import SessionLocal
from app.karaoke.compresor_audio import CompresorAudio
from app.karaoke.video_karaoke import (
    generar_karaoke_desde_main,
    get_video_resolution,
)
from app.models import Job, Media
from app.notificaciones.notificador import Notificador
from app.separacion.separador_demucs import SeparadorDemucs
from app.separacion.separador_spleeter import SeparadorSpleeter
from app.subtitles import config_video_desde_resolucion, convertir_srt_a_ass

INTERVALO_SEG = float(os.getenv("TRABAJADOR_INTERVALO_SEG", "2"))
# Cada cuanto se comprueba si el trabajo en proceso fue cancelado
INTERVALO_CANCELACION_SEG = 1


class Trabajador:
    def __init__(
        self,
        intervalo: float = INTERVALO_SEG,
        separadores=None,
        notificador=None,
    ):
        self.intervalo = intervalo
        # Demucs es el modelo principal y Spleeter el respaldo automatico
        self.separadores = separadores or [
            SeparadorDemucs(),
            SeparadorSpleeter(),
        ]
        self.notificador = notificador or Notificador()
        self.compresor = CompresorAudio()
        self._apagar = False
        self._proceso_actual = None

    def apagar(self, *_):
        """Detiene el servicio al terminar el paso en curso."""
        print("[trabajador] deteniendo...")
        self._apagar = True

    def ejecutar(self) -> None:
        crear_directorios()
        self.recuperar_trabajos_tras_reinicio()
        print(f"[trabajador] esperando trabajos (cada {self.intervalo:g} s)")
        while not self._apagar:
            try:
                if not self.procesar_siguiente():
                    time.sleep(self.intervalo)
            except Exception:
                # Un fallo de la base de datos no debe detener el servicio
                traceback.print_exc()
                time.sleep(self.intervalo)
        print("[trabajador] detenido")

    def recuperar_trabajos_tras_reinicio(self) -> None:
        with SessionLocal() as db:
            for job_id in ColaTrabajos(db).recuperar_trabajos_tras_reinicio():
                self.eliminar_archivos_parciales(db, job_id)

    def eliminar_archivos_parciales(self, db, job_id: str) -> None:
        """Borra los archivos y registros de un trabajo que no termino."""
        db.query(Media).filter(Media.job_id == job_id).delete()
        db.commit()
        eliminar_rutas(archivos_del_trabajo(job_id))

    def _cancelado(self, job_id: str) -> bool:
        with SessionLocal() as db:
            return ColaTrabajos(db).esta_cancelado(job_id)

    def comprobar_cancelacion(self, job_id: str) -> None:
        if self._cancelado(job_id):
            raise TrabajoCancelado()

    def detener(self, job_id: str) -> None:
        """Termina el programa externo en curso y sus subprocesos."""
        proceso = self._proceso_actual
        if proceso is None or proceso.poll() is not None:
            return
        print(f"[job {job_id}] cancelado: deteniendo el procesamiento")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proceso.pid)],
                capture_output=True,
            )
        else:
            os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
        proceso.wait()

    def _ejecutar(
        self, job_id: str, cmd, cwd=None, salida=None, entorno=None
    ) -> None:
        """Ejecuta un programa externo; lo detiene si se cancela el trabajo."""
        self._proceso_actual = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=entorno,
            stdout=salida,
            stderr=subprocess.STDOUT if salida else None,
            start_new_session=os.name != "nt",
        )
        try:
            while True:
                try:
                    codigo = self._proceso_actual.wait(
                        timeout=INTERVALO_CANCELACION_SEG
                    )
                    break
                except subprocess.TimeoutExpired:
                    if self._cancelado(job_id):
                        self.detener(job_id)
                        raise TrabajoCancelado()
        finally:
            self._proceso_actual = None
        if codigo != 0:
            raise subprocess.CalledProcessError(codigo, cmd)

    def separar(self, job_id: str, audio: str, carpeta: str):
        """Separa la voz con el primer modelo que funcione.

        Devuelve el resultado y el nombre del modelo utilizado.
        """
        for i, separador in enumerate(self.separadores):
            try:
                resultado = separador.separar(
                    audio,
                    carpeta,
                    lambda cmd, entorno=None: self._ejecutar(
                        job_id, cmd, entorno=entorno
                    ),
                )
                return resultado, separador.nombre
            except TrabajoCancelado:
                raise
            except Exception as e:
                if i == len(self.separadores) - 1:
                    raise
                print(
                    f"[job {job_id}] {separador.nombre} fallo ({e}); "
                    "se usa el modelo de respaldo"
                )

    def procesar_siguiente(self) -> bool:
        """Procesa el siguiente trabajo en cola.

        Devuelve False si no habia ninguno.
        """
        with SessionLocal() as db:
            cola = ColaTrabajos(db)
            job = cola.siguiente()
            if job is None:
                db.rollback()
                return False
            cola.marcar_procesando(job)
            print(f"[trabajador] procesando {job.id} ({job.source_filename})")
            self.procesar(cola, job)
            # Terminado o con error: se avisa al celular del usuario (Pb-4)
            db.refresh(job)
            self.notificador.notificar_fin(cola, job)
            return True

    def procesar(self, cola: ColaTrabajos, job: Job) -> None:
        job_id = job.id
        extension = os.path.splitext(job.source_filename)[1].lower()
        input_temp = ruta_origen(job_id, extension)
        output_dir = f"output_{job_id}"
        audio_file = os.path.join(DIR_AUDIOS, f"{job_id}.wav")
        video_sin_audio_file = os.path.join(
            DIR_VIDEOS, f"{job_id}_sin_audio.mp4"
        )
        final_filename = ruta_instrumental(job_id)
        srt_path = os.path.join(DIR_SRT, f"{job_id}.srt")
        ass_path = os.path.join(DIR_ASS, f"{job_id}.ass")
        audio_permanent_dir = os.path.join(DIR_AUDIOS, job_id)
        permanent_instrumental = os.path.join(
            audio_permanent_dir, "accompaniment.wav"
        )
        permanent_vocals = os.path.join(audio_permanent_dir, "vocals.wav")
        # Pistas comprimidas del Modo Karaoke (Pb-6)
        reproduccion_instrumental = ruta_pista_comprimida(
            job_id, "instrumental"
        )
        reproduccion_voz = ruta_pista_comprimida(job_id, "voz")
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
            self._ejecutar(
                job_id,
                [
                    "ffmpeg",
                    "-i",
                    input_temp,
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    audio_file,
                    "-y",
                ],
            )
            self._ejecutar(
                job_id,
                [
                    "ffmpeg",
                    "-i",
                    input_temp,
                    "-c",
                    "copy",
                    "-an",
                    video_sin_audio_file,
                    "-y",
                ],
            )
            cola.registrar_archivo(job, audio_file, "wav", "audio")
            cola.registrar_archivo(job, video_sin_audio_file, "mp4", "video")

            # 2) Separacion de voces
            cola.avanzar(job, "separando_voces", 15)
            separacion, modelo = self.separar(job_id, audio_file, output_dir)
            cola.registrar_modelo(job, modelo)
            instrumental_path = separacion.instrumental
            vocals_path = separacion.voz

            os.makedirs(audio_permanent_dir, exist_ok=True)
            shutil.copy2(instrumental_path, permanent_instrumental)
            shutil.copy2(vocals_path, permanent_vocals)
            cola.registrar_archivo(
                job, permanent_instrumental, "wav", "audio_instrumental"
            )
            cola.registrar_archivo(
                job, permanent_vocals, "wav", "audio_vocals"
            )
            ejecutar = lambda cmd: self._ejecutar(job_id, cmd)  # noqa: E731
            self.compresor.comprimir(
                permanent_instrumental, reproduccion_instrumental, ejecutar
            )
            self.compresor.comprimir(
                permanent_vocals, reproduccion_voz, ejecutar
            )
            cola.registrar_archivo(
                job, reproduccion_instrumental, "m4a", "playback_instrumental"
            )
            cola.registrar_archivo(
                job, reproduccion_voz, "m4a", "playback_vocals"
            )

            # 3) Video instrumental
            cola.avanzar(job, "generando_instrumental", 40)
            self._ejecutar(
                job_id,
                [
                    "ffmpeg",
                    "-i",
                    video_sin_audio_file,
                    "-i",
                    instrumental_path,
                    "-c:v",
                    "copy",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    final_filename,
                    "-y",
                ],
            )
            cola.registrar_archivo(
                job, final_filename, "mp4", "video_instrumental"
            )

            # 4) Subtitulos y video karaoke, salvo que se pidiera solo el
            #    instrumental; si fallan, queda el instrumental
            if job.video_type != "instrumental":
                try:
                    video_karaoke_path = self.transcribir_y_generar_karaoke(
                        cola,
                        job,
                        vocals_path,
                        audio_file,
                        final_filename,
                        srt_path,
                        ass_path,
                    )
                except Exception as e:
                    print(f"[job {job_id}] ERROR en subtitulos/karaoke: {e}")
                    traceback.print_exc()

            # Un fallo en la etapa anterior puede deberse a una cancelacion
            self.comprobar_cancelacion(job_id)
            cola.marcar_terminado(
                job,
                [
                    audio_file,
                    permanent_instrumental,
                    permanent_vocals,
                    reproduccion_instrumental,
                    reproduccion_voz,
                    final_filename,
                ],
                "karaoke" if video_karaoke_path else "instrumental",
            )
            print(f"[trabajador] {job_id} terminado")

        except TrabajoCancelado:
            cola.db.rollback()
            print(f"[job {job_id}] cancelado por el usuario")
            self.eliminar_archivos_parciales(cola.db, job_id)

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

    def transcribir_y_generar_karaoke(
        self,
        cola,
        job,
        vocals_path,
        audio_file,
        final_filename,
        srt_path,
        ass_path,
    ):
        """Transcribe la voz, genera los subtitulos y compone el karaoke."""
        cola.avanzar(job, "transcribiendo", 45)
        whisperx_py = os.getenv("WHISPERX_PY") or ejecutable_venv(
            "venv_torch", "python"
        )
        audio_in = vocals_path if os.path.exists(vocals_path) else audio_file
        script_path = os.path.join(DIR_PROYECTO, "app", "whisperx_run.py")
        with tempfile.TemporaryFile(mode="w+") as log:
            try:
                self._ejecutar(
                    job.id,
                    [
                        whisperx_py,
                        script_path,
                        "--audio",
                        audio_in,
                        "--srt",
                        srt_path,
                        "--letra",
                        ruta_letra(job.id),
                    ],
                    cwd=DIR_PROYECTO,
                    salida=log,
                )
            except subprocess.CalledProcessError:
                log.seek(0)
                print(log.read()[-2000:])
                raise RuntimeError("WhisperX fallo")
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"WhisperX no genero el SRT: {srt_path}")

        cola.avanzar(job, "generando_subtitulos", 78)
        resolucion = get_video_resolution(final_filename) or (1920, 1080)
        convertir_srt_a_ass(
            srt_path,
            ass_path,
            cfg_video=config_video_desde_resolucion(*resolucion),
        )
        cola.registrar_archivo(job, srt_path, "srt", "subtitle")
        cola.registrar_archivo(job, ass_path, "ass", "subtitle")
        if os.path.exists(ruta_letra(job.id)):
            cola.registrar_archivo(job, ruta_letra(job.id), "json", "lyrics")

        if not os.path.exists(ass_path):
            return None
        cola.avanzar(job, "generando_karaoke", 85)
        resultado_karaoke = generar_karaoke_desde_main(
            job.id, lambda cmd, log: self._ejecutar(job.id, cmd, salida=log)
        )
        if not resultado_karaoke["success"]:
            print(
                f"[job {job.id}] Error karaoke: "
                f"{resultado_karaoke.get('error')}"
            )
            return None
        video_karaoke_path = resultado_karaoke["video_karaoke_path"]
        cola.registrar_archivo(job, video_karaoke_path, "mp4", "video_karaoke")
        return video_karaoke_path


def main() -> None:
    trabajador = Trabajador()
    signal.signal(signal.SIGTERM, trabajador.apagar)
    signal.signal(signal.SIGINT, trabajador.apagar)
    trabajador.ejecutar()


if __name__ == "__main__":
    main()
