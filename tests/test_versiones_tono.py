"""Tabla de las versiones de tono de cada cancion (Pb-11, Sp-8)."""

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.database import engine
from app.models import Job, ToneVersion


def _cancion(db, usuario):
    job = Job(
        id=str(uuid.uuid4()),
        user_id=usuario.id,
        source_filename="cancion.mp4",
        status="done",
    )
    db.add(job)
    db.commit()
    return job


def _version(job, semitonos=2, pista="instrumental"):
    return ToneVersion(
        job_id=job.id,
        semitones=semitonos,
        track=pista,
        path=f"media/audios/{job.id}/tonos/{pista}_{semitonos}.m4a",
    )


def test_la_tabla_tiene_las_restricciones_del_diseno():
    inspector = inspect(engine)
    unicas = {
        u["name"] for u in inspector.get_unique_constraints("tone_versions")
    }
    checks = {
        c["name"] for c in inspector.get_check_constraints("tone_versions")
    }
    claves = {f["name"] for f in inspector.get_foreign_keys("tone_versions")}

    assert "uq_tone_versions" in unicas
    assert {
        "ck_tone_versions_semitones",
        "ck_tone_versions_track",
    } <= checks
    assert claves == {"fk_tone_versions_job"}


def test_guarda_una_version_por_cancion_tono_y_pista(db, usuario):
    job = _cancion(db, usuario)
    db.add_all([_version(job), _version(job, pista="vocals")])
    db.commit()

    db.add(_version(job))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize(
    "semitonos, pista", [(0, "instrumental"), (7, "vocals"), (2, "bateria")]
)
def test_rechaza_tonos_y_pistas_fuera_del_rango(db, usuario, semitonos, pista):
    job = _cancion(db, usuario)
    db.add(_version(job, semitonos, pista))

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_al_eliminar_la_cancion_se_eliminan_sus_versiones(db, usuario):
    job = _cancion(db, usuario)
    db.add(_version(job, -3))
    db.commit()

    db.delete(job)
    db.commit()

    assert db.query(ToneVersion).count() == 0
