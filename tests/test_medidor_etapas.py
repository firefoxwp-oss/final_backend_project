"""Tiempo de cada etapa del procesamiento (mejora del Sprint 3, Sp-20)."""

import json
import os
import uuid

import pytest

from app.archivos import ruta_tiempos
from app.cola.cola_trabajos import ColaTrabajos
from app.cola.medidor_etapas import MedidorEtapas
from app.models import Job


class _Reloj:
    """Reloj simulado: la prueba decide cuanto pasa en cada etapa."""

    def __init__(self):
        self.ahora = 100.0

    def __call__(self):
        return self.ahora


@pytest.fixture
def job_id():
    identificador = str(uuid.uuid4())
    yield identificador
    if os.path.exists(ruta_tiempos(identificador)):
        os.remove(ruta_tiempos(identificador))


def test_mide_cada_etapa_y_su_parte_del_total(job_id):
    reloj = _Reloj()
    medidor = MedidorEtapas(job_id, reloj)
    reloj.ahora += 2
    medidor.etapa("extrayendo_audio")
    reloj.ahora += 8
    medidor.etapa("separando_voces")
    reloj.ahora += 30
    medidor.etapa("transcribiendo")
    reloj.ahora += 60

    resumen = medidor.terminar(duracion_audio=240)

    assert resumen["total_segundos"] == 100
    assert [(e["etapa"], e["segundos"]) for e in resumen["etapas"]] == [
        ("extrayendo_audio", 8),
        ("separando_voces", 30),
        ("transcribiendo", 60),
    ]
    assert resumen["etapas"][2]["porcentaje"] == 60
    with open(ruta_tiempos(job_id), encoding="utf-8") as f:
        assert json.load(f)["duracion_audio_segundos"] == 240


def test_la_cola_avisa_cada_etapa_nueva(db, usuario):
    job = Job(
        id=str(uuid.uuid4()), user_id=usuario.id, source_filename="c.mp4"
    )
    ColaTrabajos(db).encolar(job)
    etapas = []
    cola = ColaTrabajos(db, al_avanzar=etapas.append)

    cola.avanzar(job, "separando_voces", 15)
    cola.avanzar(job, "transcribiendo", 45)

    assert etapas == ["separando_voces", "transcribiendo"]


@pytest.mark.lento
def test_el_trabajador_guarda_los_tiempos(servidor, token, video_corto):
    from app.cola.trabajador import Trabajador
    from tests.test_subida import _subir

    job_id = _subir(servidor, token, video_corto).json()["job_id"]
    try:
        assert Trabajador().procesar_siguiente() is True
        with open(ruta_tiempos(job_id), encoding="utf-8") as f:
            resumen = json.load(f)
        etapas = [e["etapa"] for e in resumen["etapas"]]
        assert etapas[:3] == [
            "extrayendo_audio",
            "separando_voces",
            "generando_instrumental",
        ]
        assert "transcribiendo" in etapas
        assert resumen["total_segundos"] > 0
    finally:
        if os.path.exists(ruta_tiempos(job_id)):
            os.remove(ruta_tiempos(job_id))
