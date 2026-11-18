"""Registro con aceptación de los términos y la política de privacidad."""

import requests

from app.models import User


def _registrar(servidor, **extra):
    datos = {"name": "Ana", "email": "ana@test.com", "password": "secreta123"}
    return requests.post(f"{servidor}/register", json={**datos, **extra})


def test_sin_aceptar_los_terminos_no_se_crea_la_cuenta(servidor, db):
    respuesta = _registrar(servidor)

    assert respuesta.status_code == 400
    assert "términos" in respuesta.json()["detail"]
    assert db.query(User).count() == 0


def test_al_aceptar_los_terminos_se_guarda_la_fecha(servidor, db):
    respuesta = _registrar(servidor, acepta_terminos=True)

    assert respuesta.status_code == 200
    assert db.query(User).one().terminos_aceptados_en is not None
