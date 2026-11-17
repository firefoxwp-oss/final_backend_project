"""Configuracion de Firebase Cloud Messaging (Sp-1)."""

import pytest

from app.notificaciones.firebase import ConfiguracionFirebase

VARIABLES = ("FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL")


def test_sin_variables_no_hay_configuracion(monkeypatch):
    for nombre in VARIABLES + ("FIREBASE_PRIVATE_KEY",):
        monkeypatch.delenv(nombre, raising=False)
    assert ConfiguracionFirebase.desde_entorno() is None


@pytest.mark.red
def test_la_cuenta_de_servicio_obtiene_un_token():
    configuracion = ConfiguracionFirebase.desde_entorno()
    if configuracion is None:
        pytest.skip("Firebase no esta configurado en el .env")
    assert configuracion.url_envio.endswith("/messages:send")
    assert configuracion.token_acceso()
