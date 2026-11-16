"""Conexion con Firebase Cloud Messaging (API HTTP v1).

Las credenciales de la cuenta de servicio del proyecto de Firebase se leen
del .env: FIREBASE_PROJECT_ID, FIREBASE_CLIENT_EMAIL y FIREBASE_PRIVATE_KEY
(con los saltos de linea escritos como \\n).
"""

import os

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

load_dotenv()

ALCANCE = "https://www.googleapis.com/auth/firebase.messaging"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_ENVIO = "https://fcm.googleapis.com/v1/projects/{}/messages:send"


class ConfiguracionFirebase:
    """Cuenta de servicio con permiso para enviar notificaciones."""

    def __init__(self, project_id: str, client_email: str, private_key: str):
        self.project_id = project_id
        self.url_envio = URL_ENVIO.format(project_id)
        self._credenciales = Credentials.from_service_account_info(
            {
                "type": "service_account",
                "project_id": project_id,
                "client_email": client_email,
                "private_key": private_key,
                "token_uri": URL_TOKEN,
            },
            scopes=[ALCANCE],
        )

    @classmethod
    def desde_entorno(cls):
        """Configuracion del .env, o None si Firebase no esta configurado.

        Sin Firebase el sistema sigue funcionando: el estado de los trabajos
        se consulta en la web y en la aplicacion (RF-09).
        """
        datos = [
            os.getenv(nombre)
            for nombre in (
                "FIREBASE_PROJECT_ID",
                "FIREBASE_CLIENT_EMAIL",
                "FIREBASE_PRIVATE_KEY",
            )
        ]
        if not all(datos):
            return None
        project_id, client_email, private_key = datos
        return cls(project_id, client_email, private_key.replace("\\n", "\n"))

    def token_acceso(self) -> str:
        """Token OAuth 2.0 para la API de FCM; se renueva al vencer."""
        if not self._credenciales.valid:
            self._credenciales.refresh(Request())
        return self._credenciales.token
