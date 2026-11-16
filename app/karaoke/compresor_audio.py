"""Compresion de las pistas para el Modo Karaoke.

El reproductor usa audio comprimido (AAC en contenedor M4A, unos 4 MB por
cancion de 4 minutos frente a 43 MB del WAV); los WAV se reservan para las
descargas (RR-06).
"""

import os

from app.separacion.separador_voz import ejecutar_proceso

BITRATE = os.getenv("KARAOKE_AUDIO_BITRATE", "128k")


class CompresorAudio:
    def __init__(self, bitrate: str = BITRATE):
        self.bitrate = bitrate

    def comprimir(self, wav: str, destino: str, ejecutar=ejecutar_proceso):
        """Genera `destino` (.m4a) a partir de `wav` y devuelve su ruta."""
        ejecutar(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                wav,
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                self.bitrate,
                "-movflags",
                "+faststart",
                destino,
                "-y",
            ]
        )
        if not os.path.exists(destino):
            raise RuntimeError(f"No se genero el audio comprimido {destino}")
        return destino
