"""Pruebas del plan freemium: límite mensual del plan gratuito."""

import uuid
from datetime import datetime, timedelta, timezone

import requests

from app.models import LIMITE_PLAN_GRATUITO, Job


def _trabajos(db, usuario, cantidad, estado="done", creado=None):
    for _ in range(cantidad):
        job = Job(
            id=str(uuid.uuid4()),
            user_id=usuario.id,
            source_filename="cancion.mp4",
            status=estado,
        )
        if creado is not None:
            job.created_at = creado
        db.add(job)
    db.commit()


def _subir(servidor, token, ruta):
    with open(ruta, "rb") as archivo:
        return requests.post(
            f"{servidor}/procesar-video/",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("cancion.mp4", archivo)},
            timeout=60,
        )


def _yo(servidor, token):
    return requests.get(
        f"{servidor}/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    ).json()


def test_un_usuario_nuevo_tiene_el_plan_gratuito_con_su_cupo(servidor, token):
    yo = _yo(servidor, token)

    assert yo["plan"] == "gratuito"
    assert yo["canciones_restantes"] == LIMITE_PLAN_GRATUITO


def test_al_agotar_el_cupo_rechaza_la_subida_con_un_mensaje(
    servidor, token, db, usuario, video_corto
):
    _trabajos(db, usuario, LIMITE_PLAN_GRATUITO)

    respuesta = _subir(servidor, token, video_corto)

    assert respuesta.status_code == 403
    assert "plan Gratuito" in respuesta.json()["detail"]
    assert _yo(servidor, token)["canciones_restantes"] == 0


def test_no_cuentan_los_cancelados_ni_los_de_meses_anteriores(
    servidor, token, db, usuario, video_corto
):
    _trabajos(db, usuario, 2, estado="cancelled")
    _trabajos(db, usuario, 1, estado="error")
    mes_pasado = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    _trabajos(db, usuario, LIMITE_PLAN_GRATUITO, creado=mes_pasado)

    assert _yo(servidor, token)["canciones_restantes"] == LIMITE_PLAN_GRATUITO
    assert _subir(servidor, token, video_corto).status_code == 202


def test_el_plan_premium_no_tiene_limite(
    servidor, token, db, usuario, video_corto
):
    usuario.plan = "premium"
    db.commit()
    _trabajos(db, usuario, LIMITE_PLAN_GRATUITO + 2)

    assert _yo(servidor, token)["canciones_restantes"] is None
    assert _subir(servidor, token, video_corto).status_code == 202
