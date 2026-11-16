"""Descarga los modelos preentrenados en `pretrained_models/`.

Con estos archivos el sistema procesa sin conexion: Demucs, Spleeter y
WhisperX los cargan desde aqui y no descargan nada. Se ejecuta una vez al
instalar el servidor, con el Python del entorno de PyTorch:

    venv_torch/bin/python pretrained_models/descargar_modelos.py
    venv_torch/bin/python pretrained_models/descargar_modelos.py --dataset

Con `--dataset` descarga tambien MUSDB18 (fragmentos de 7 s), el dataset de
los cuadernos de fine-tuning.
"""

import argparse
import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DIR = Path(__file__).resolve().parent

DEMUCS_URL = (
    "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/"
    "955717e8-8726e21a.th"
)
SPLEETER_URL = (
    "https://github.com/deezer/spleeter/releases/download/v1.4.0/"
    "2stems.tar.gz"
)
DATASET_URL = (
    "https://zenodo.org/records/3270814/files/MUSDB18-7-STEMS.zip?download=1"
)
DATASET_MD5 = "dc2bdfac5b46ce742bd60009866758a5"

# Repositorio de Hugging Face, revision fijada y archivos necesarios
WHISPER = (
    "Systran/faster-whisper-large-v2",
    "f0fe81560cb8b68660e564f55dd99207059c092e",
    ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
)
ALINEADOR = (
    "jonatasgrosman/wav2vec2-large-xlsr-53-spanish",
    "80106547eee5065e01618d6588c22c256e8d0e70",
    [
        "config.json",
        "model.safetensors",
        "preprocessor_config.json",
        "special_tokens_map.json",
        "vocab.json",
    ],
)


def descargar(url: str, destino: Path) -> Path:
    print(f"Descargando {url}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".parcial")
    with urllib.request.urlopen(url) as r, open(temporal, "wb") as f:
        shutil.copyfileobj(r, f)
    temporal.replace(destino)
    return destino


def resumen(ruta: Path, algoritmo: str) -> str:
    h = hashlib.new(algoritmo)
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def demucs() -> None:
    carpeta = DIR / "demucs" / "modelo"
    pesos = carpeta / DEMUCS_URL.rsplit("/", 1)[1]
    if not pesos.exists():
        descargar(DEMUCS_URL, pesos)
    # El nombre del archivo termina con el inicio de su SHA-256
    if not resumen(pesos, "sha256").startswith(pesos.stem.split("-")[1]):
        pesos.unlink()
        raise RuntimeError("Checksum incorrecto en los pesos de Demucs")
    (carpeta / "htdemucs.yaml").write_text("models: ['955717e8']\n")
    print("Demucs listo:", carpeta)


def spleeter() -> None:
    carpeta = DIR / "spleeter" / "modelo" / "2stems"
    if not (carpeta / ".probe").exists():
        with tempfile.TemporaryDirectory() as tmp:
            archivo = descargar(SPLEETER_URL, Path(tmp) / "2stems.tar.gz")
            carpeta.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archivo) as tar:
                for miembro in tar.getmembers():
                    ruta = (carpeta / miembro.name).resolve()
                    if carpeta.resolve() not in ruta.parents:
                        raise RuntimeError(f"Ruta no valida: {miembro.name}")
                tar.extractall(carpeta)
        (carpeta / ".probe").write_text("OK")
    print("Spleeter listo:", carpeta)


def whisperx() -> None:
    import nltk
    from huggingface_hub import snapshot_download

    carpeta = DIR / "whisperx" / "modelo"
    for repo, revision, archivos in (WHISPER, ALINEADOR):
        destino = carpeta / repo.split("/")[1]
        snapshot_download(
            repo,
            revision=revision,
            allow_patterns=archivos,
            local_dir=destino,
        )
        print("WhisperX listo:", destino)
    nltk.download("punkt_tab", download_dir=str(carpeta / "nltk_data"))


def dataset() -> None:
    destinos = [
        DIR / modelo / "dataset" / "musdb18-7s"
        for modelo in ("demucs", "spleeter")
    ]
    if all((d / "train").is_dir() for d in destinos):
        print("Dataset listo")
        return
    with tempfile.TemporaryDirectory() as tmp:
        archivo = descargar(DATASET_URL, Path(tmp) / "MUSDB18-7-STEMS.zip")
        if resumen(archivo, "md5") != DATASET_MD5:
            raise RuntimeError("Checksum incorrecto en el dataset")
        for destino in destinos:
            with zipfile.ZipFile(archivo) as z:
                z.extractall(destino)
            print("Dataset listo:", destino)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dataset", action="store_true", help="descarga tambien MUSDB18"
    )
    args = parser.parse_args()
    demucs()
    spleeter()
    whisperx()
    if args.dataset:
        dataset()


if __name__ == "__main__":
    main()
