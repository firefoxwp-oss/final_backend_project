"""Notificador: avisa al celular del usuario que su procesamiento termino.

Envia la notificacion con Firebase Cloud Messaging a cada celular registrado
por el dueno del trabajo (Pb-4). Si FCM indica que un token ya no es valido,
el celular se elimina. Un fallo en el envio no afecta al trabajo: su estado
sigue disponible en la web y en la aplicacion (RF-09).
"""

import requests

from app.cola.cola_trabajos import ColaTrabajos
from app.models import Device, Job
from app.notificaciones.firebase import ConfiguracionFirebase

# Canal de notificaciones de la aplicacion movil
CANAL_ANDROID = "procesamientos"


def _enviar_http(url: str, token_acceso: str, mensaje: dict):
    return requests.post(
        url,
        headers={"Authorization": f"Bearer {token_acceso}"},
        json={"message": mensaje},
        timeout=10,
    )


def _token_invalido(respuesta) -> bool:
    """FCM responde 404 (UNREGISTERED) si la aplicacion se desinstalo, y 400
    si el token no tiene el formato de un token de registro."""
    if respuesta.status_code == 404:
        return True
    if respuesta.status_code == 400:
        try:
            detalle = respuesta.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            return False
        return "registration token" in detalle
    return False


class Notificador:
    def __init__(self, configuracion=None, enviar=_enviar_http):
        self.configuracion = configuracion or (
            ConfiguracionFirebase.desde_entorno()
        )
        self.enviar = enviar

    @staticmethod
    def mensaje(job: Job, token: str) -> dict:
        """Titulo y texto segun el resultado; los datos abren la cancion."""
        if job.status == "done":
            titulo = "Tu canción está lista"
            texto = f"{job.source_filename} ya se puede cantar"
        else:
            titulo = "No se pudo procesar tu canción"
            texto = f"{job.source_filename}: revisa el motivo en la app"
        return {
            "token": token,
            "notification": {"title": titulo, "body": texto},
            "data": {"job_id": job.id, "status": job.status},
            "android": {
                "priority": "high",
                "notification": {"channel_id": CANAL_ANDROID},
            },
        }

    def dispositivos_del_usuario(self, db, usuario_id: int) -> list:
        return db.query(Device).filter(Device.user_id == usuario_id).all()

    def eliminar_dispositivo(self, db, dispositivo: Device) -> None:
        db.delete(dispositivo)
        db.commit()
        print(f"[notificador] token no valido eliminado ({dispositivo.id})")

    def notificar_fin(self, cola: ColaTrabajos, job: Job) -> int:
        """Notifica el fin del trabajo; devuelve cuantos celulares lo
        recibieron."""
        if self.configuracion is None or job.status not in ("done", "error"):
            return 0
        dispositivos = self.dispositivos_del_usuario(cola.db, job.user_id)
        if not dispositivos:
            return 0
        enviados = 0
        try:
            token_acceso = self.configuracion.token_acceso()
            for dispositivo in dispositivos:
                respuesta = self.enviar(
                    self.configuracion.url_envio,
                    token_acceso,
                    self.mensaje(job, dispositivo.token),
                )
                if respuesta.status_code == 200:
                    enviados += 1
                elif _token_invalido(respuesta):
                    self.eliminar_dispositivo(cola.db, dispositivo)
                else:
                    print(
                        f"[notificador] FCM respondio "
                        f"{respuesta.status_code}: {respuesta.text[:200]}"
                    )
        except Exception as e:  # sin conexion o credenciales no validas
            print(f"[notificador] no se pudo notificar {job.id}: {e}")
        if enviados:
            cola.marcar_notificado(job)
        return enviados
