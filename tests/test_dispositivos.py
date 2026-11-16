"""Registro de los celulares que reciben notificaciones (Pb-4, Sp-2)."""

import requests

from app.auth import get_password_hash
from app.models import Device, User

TOKEN_FCM = "fcm-token-de-prueba:APA91b" + "x" * 140


def _cabecera(token):
    return {"Authorization": f"Bearer {token}"}


def _registrar(servidor, token, token_fcm=TOKEN_FCM, plataforma="android"):
    return requests.post(
        f"{servidor}/dispositivos",
        headers=_cabecera(token),
        json={"token": token_fcm, "platform": plataforma},
        timeout=10,
    )


def _otro_usuario(db, servidor):
    db.add(
        User(
            name="Otra",
            email="otra@test.com",
            password=get_password_hash("secreta123"),
        )
    )
    db.commit()
    respuesta = requests.post(
        f"{servidor}/login",
        json={"email": "otra@test.com", "password": "secreta123"},
        timeout=10,
    )
    return respuesta.json()["access_token"]


def test_registrar_el_celular(servidor, token, usuario, db):
    respuesta = _registrar(servidor, token)
    assert respuesta.status_code == 201
    assert respuesta.json()["platform"] == "android"
    dispositivo = db.query(Device).one()
    assert dispositivo.user_id == usuario.id
    assert dispositivo.token == TOKEN_FCM


def test_registrar_dos_veces_no_duplica(servidor, token, db):
    _registrar(servidor, token)
    assert _registrar(servidor, token).status_code == 201
    assert db.query(Device).count() == 1


def test_otro_usuario_en_el_mismo_celular(servidor, token, usuario, db):
    _registrar(servidor, token)
    otro = _otro_usuario(db, servidor)
    assert _registrar(servidor, otro).status_code == 201
    db.expire_all()
    dispositivo = db.query(Device).one()
    assert dispositivo.user_id != usuario.id


def test_eliminar_al_cerrar_sesion(servidor, token, db):
    _registrar(servidor, token)
    url = f"{servidor}/dispositivos/{TOKEN_FCM}"
    assert requests.delete(url, headers=_cabecera(token)).status_code == 204
    assert db.query(Device).count() == 0
    # Repetir la peticion no falla
    assert requests.delete(url, headers=_cabecera(token)).status_code == 204


def test_no_se_elimina_el_celular_de_otro_usuario(servidor, token, db):
    _registrar(servidor, token)
    otro = _otro_usuario(db, servidor)
    requests.delete(
        f"{servidor}/dispositivos/{TOKEN_FCM}", headers=_cabecera(otro)
    )
    assert db.query(Device).count() == 1


def test_requiere_sesion_y_plataforma_valida(servidor, token):
    sin_sesion = requests.post(
        f"{servidor}/dispositivos", json={"token": TOKEN_FCM}, timeout=10
    )
    assert sin_sesion.status_code in (401, 403)
    assert _registrar(servidor, token, plataforma="ios").status_code == 400
