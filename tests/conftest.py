"""Configuracion comun de las pruebas.

Las pruebas usan su propia base de datos (TEST_DB_NAME, por defecto
media_db_test), que se crea si no existe y se vacia antes de cada prueba.
"""

import os
import socket
import subprocess
import sys
import time

import psycopg2
import pytest
import requests
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()
os.environ["DB_NAME"] = os.getenv("TEST_DB_NAME", "media_db_test")

from app.archivos import archivos_del_trabajo, eliminar_rutas  # noqa: E402
from app.auth import get_password_hash  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.migrate import aplicar_migraciones  # noqa: E402
from app.models import Base, Job, User  # noqa: E402

DIR_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAVE = "secreta123"


def _crear_base_si_no_existe():
    conexion = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname="postgres",
    )
    conexion.autocommit = True
    with conexion.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (os.environ["DB_NAME"],),
        )
        if cursor.fetchone() is None:
            cursor.execute(f'CREATE DATABASE "{os.environ["DB_NAME"]}"')
    conexion.close()


@pytest.fixture(scope="session", autouse=True)
def esquema():
    _crear_base_si_no_existe()
    Base.metadata.create_all(bind=engine)
    aplicar_migraciones(engine)


def _vaciar_base():
    """Borra los datos de la base de pruebas y los archivos de sus trabajos."""
    with SessionLocal() as db:
        ids = [j.id for j in db.query(Job).all()]
        db.execute(
            text(
                "TRUNCATE media, jobs, proyecto, users "
                "RESTART IDENTITY CASCADE"
            )
        )
        db.commit()
    for job_id in ids:
        eliminar_rutas(archivos_del_trabajo(job_id))


@pytest.fixture(autouse=True)
def base_limpia(esquema):
    _vaciar_base()
    yield
    _vaciar_base()


@pytest.fixture
def db():
    with SessionLocal() as sesion:
        yield sesion


@pytest.fixture
def usuario(db):
    user = User(
        name="Prueba",
        email="prueba@test.com",
        password=get_password_hash(CLAVE),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def servidor(esquema):
    """API real en un puerto libre, conectada a la base de pruebas."""
    puerto = _puerto_libre()
    proceso = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(puerto),
        ],
        cwd=DIR_PROYECTO,
        env=dict(os.environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(60):
        try:
            requests.get(url, timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.5)
    yield url
    proceso.terminate()
    proceso.wait(timeout=10)


@pytest.fixture
def token(servidor, usuario):
    respuesta = requests.post(
        f"{servidor}/login",
        json={"email": usuario.email, "password": CLAVE},
        timeout=10,
    )
    return respuesta.json()["access_token"]


def _generar_video(ruta, segundos):
    """Video generado con FFmpeg: imagen fija y un tono."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=320x240:d={segundos}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={segundos}",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(ruta),
            "-y",
        ],
        check=True,
    )
    return ruta


@pytest.fixture(scope="session")
def video_largo(tmp_path_factory):
    """Video de 60 s, para cancelar mientras se procesa."""
    ruta = tmp_path_factory.mktemp("videos") / "largo.mp4"
    return _generar_video(ruta, 60)


@pytest.fixture(scope="session")
def video_corto(tmp_path_factory):
    """Video de 8 s generado con FFmpeg (imagen fija y un tono)."""
    ruta = tmp_path_factory.mktemp("videos") / "cancion.mp4"
    return _generar_video(ruta, 8)
