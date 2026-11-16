import argparse
import os
import sys
from pathlib import Path


def env(name, default=None):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def as_int(name, default):
    try:
        value = env(name)
        return int(value) if value is not None else default
    except Exception:
        return default


def as_float(name, default):
    try:
        value = env(name)
        return float(value) if value is not None else default
    except Exception:
        return default


# Modelo de alineacion por idioma. Para espanol, WhisperX usa por defecto
# VOXPOPULI_ASR_BASE_10K_ES (discursos del Parlamento Europeo, modelo "base"),
# un dominio muy alejado del canto. Este wav2vec2 "large" da timings de palabra
# bastante mas fiables sobre voz cantada.
ALIGN_MODELS = {
    "es": "jonatasgrosman/wav2vec2-large-xlsr-53-spanish",
}


def colapsar_repeticiones(word_segments, max_repeticiones=6):
    """Elimina bucles de decodificacion.

    Whisper puede quedarse repitiendo la misma palabra decenas de veces sobre
    vocales sostenidas o ad-libs. Se conservan unas pocas repeticiones
    (legitimas en una cancion) y se descarta el resto.
    """
    limpio = []
    anterior = None
    repetidas = 0
    descartadas = 0
    for w in word_segments:
        texto = (w.get("word") or "").strip().lower().strip(".,!?;:")
        if texto and texto == anterior:
            repetidas += 1
            if repetidas >= max_repeticiones:
                descartadas += 1
                continue
        else:
            anterior = texto
            repetidas = 0
        limpio.append(w)
    return limpio, descartadas


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio a SRT palabra a palabra con WhisperX."
    )
    parser.add_argument(
        "--audio", required=True, help="Ruta del audio a transcribir"
    )
    parser.add_argument(
        "--srt", required=True, help="Ruta de salida del archivo SRT"
    )
    parser.add_argument(
        "--model", default=None, help="tiny|base|small|medium|large-v2"
    )
    parser.add_argument("--device", default=None, choices=["cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--language", default=None, help="Codigo ISO (es, en, ...)"
    )
    args = parser.parse_args()

    audio_path = args.audio
    srt_path = args.srt

    # Idioma: CLI > ENV > espanol. Antes estaba fijado en el codigo e ignoraba
    # la variable WHISPERX_LANGUAGE definida en .env.
    language = args.language or env("WHISPERX_LANGUAGE") or "es"

    if not os.path.exists(audio_path):
        print(f"ERROR: No existe el audio: {audio_path}", file=sys.stderr)
        sys.exit(2)

    try:
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        print(f"[WhisperX] Audio: {audio_path}", file=sys.stderr)
        print(f"[WhisperX] Output SRT: {srt_path}", file=sys.stderr)

        import torch
        import whisperx

        from app.subtitles import segundos_a_tiempo_srt

        device = (
            args.device
            or env("WHISPERX_DEVICE")
            or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        model_name = args.model or env("WHISPERX_MODEL") or "medium"
        compute_type = env("WHISPERX_COMPUTE_TYPE") or (
            "float16" if device == "cuda" else "int8"
        )
        default_batch = 4 if device == "cpu" else 16
        batch_size = (
            args.batch_size
            if args.batch_size is not None
            else as_int("WHISPERX_BATCH", default_batch)
        )

        print(
            f"[WhisperX] device={device} model={model_name} "
            f"compute={compute_type} batch={batch_size} lang={language}",
            file=sys.stderr,
        )

        omp = as_int("OMP_NUM_THREADS", 0)
        mkl = as_int("MKL_NUM_THREADS", 0)
        if omp:
            os.environ["OMP_NUM_THREADS"] = str(omp)
        if mkl:
            os.environ["MKL_NUM_THREADS"] = str(mkl)

        # Umbrales de rechazo. Whisper alucina texto sobre el residuo musical
        # que deja la separacion de voces (frases inventadas en tramos sin
        # canto) y entra en bucle sobre notas sostenidas. Estos limites los
        # recortan.
        asr_options = {
            "compression_ratio_threshold": as_float(
                "WHISPERX_COMPRESSION_RATIO", 2.0
            ),
            "log_prob_threshold": as_float("WHISPERX_LOGPROB", -0.8),
            "no_speech_threshold": as_float("WHISPERX_NO_SPEECH", 0.75),
            "condition_on_previous_text": False,
        }
        vad_options = {
            "vad_onset": as_float("WHISPERX_VAD_ONSET", 0.55),
            "vad_offset": as_float("WHISPERX_VAD_OFFSET", 0.40),
        }

        print(f"[WhisperX] Cargando modelo {model_name}...", file=sys.stderr)
        try:
            model = whisperx.load_model(
                model_name,
                device,
                compute_type=compute_type,
                language=language,
                asr_options=asr_options,
                vad_options=vad_options,
            )
        except TypeError:
            # Compatibilidad con versiones que no aceptan estas opciones
            print(
                "[WhisperX] asr_options no soportado, usando defaults",
                file=sys.stderr,
            )
            model = whisperx.load_model(
                model_name,
                device,
                compute_type=compute_type,
                language=language,
            )

        audio = whisperx.load_audio(audio_path)
        print(
            f"[WhisperX] Audio cargado ({len(audio) / 16000:.2f}s)",
            file=sys.stderr,
        )

        result = model.transcribe(audio, batch_size=batch_size)
        print("[WhisperX] Transcripcion completada", file=sys.stderr)

        align_model_name = env("WHISPERX_ALIGN_MODEL") or ALIGN_MODELS.get(
            language
        )
        print(
            f"[WhisperX] Alineando (modelo: {align_model_name or 'default'})",
            file=sys.stderr,
        )
        try:
            align_model, metadata = whisperx.load_align_model(
                language_code=language,
                device=device,
                model_name=align_model_name,
            )
        except Exception as e:
            print(
                f"[WhisperX] Fallback al alineador por defecto: {e}",
                file=sys.stderr,
            )
            align_model, metadata = whisperx.load_align_model(
                language_code=language, device=device
            )

        aligned = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        print("[WhisperX] Alineamiento completado", file=sys.stderr)

        word_segments = aligned.get("word_segments") or []
        print(
            f"[WhisperX] Palabras alineadas: {len(word_segments)}",
            file=sys.stderr,
        )

        word_segments, descartadas = colapsar_repeticiones(word_segments)
        if descartadas:
            print(
                f"[WhisperX] Repeticiones descartadas: {descartadas}",
                file=sys.stderr,
            )

        # Numeracion correlativa: antes el indice se incrementaba tambien para
        # las palabras descartadas, dejando huecos en la numeracion del SRT.
        lines = []
        indice = 0
        sin_tiempo = 0
        for w in word_segments:
            start, end = w.get("start"), w.get("end")
            text = (w.get("word") or "").strip()
            if not text:
                continue
            if start is None or end is None:
                sin_tiempo += 1
                continue
            if end < start:
                end = start
            indice += 1
            lines.append(
                "{}\n{} --> {}\n{}\n\n".format(
                    indice,
                    segundos_a_tiempo_srt(start),
                    segundos_a_tiempo_srt(end),
                    text,
                )
            )

        if sin_tiempo:
            print(
                f"[WhisperX] Palabras sin timestamp omitidas: {sin_tiempo}",
                file=sys.stderr,
            )

        destino = os.path.dirname(srt_path)
        if destino:
            os.makedirs(destino, exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("".join(lines))

        print(f"SRT creado: {srt_path} ({indice} palabras)", file=sys.stderr)
        print(
            f"[WhisperX] device={device} model={model_name} "
            f"language={language} "
            f"palabras={indice}"
        )

    except ImportError as e:
        print(
            f"ERROR: No se pudo importar modulo requerido: {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR: Archivo no encontrado: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
