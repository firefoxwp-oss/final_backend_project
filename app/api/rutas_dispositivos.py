"""Rutas de dispositivos (RutasDispositivos): registro de los celulares que
reciben las notificaciones de finalizacion (Pb-4)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_db
from app.models import PLATAFORMAS, Device, User
from app.schemas import DispositivoRegistro, DispositivoRespuesta

router = APIRouter(tags=["dispositivos"])


@router.post(
    "/dispositivos", status_code=201, response_model=DispositivoRespuesta
)
def registrar(
    datos: DispositivoRegistro,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registra el celular al iniciar sesion.

    Si el token ya existe (la aplicacion vuelve a iniciar sesion o cambio el
    usuario del celular), se actualiza su dueno en lugar de duplicarlo.
    """
    if datos.platform not in PLATAFORMAS:
        raise HTTPException(status_code=400, detail="Plataforma no admitida")
    dispositivo = db.query(Device).filter(Device.token == datos.token).first()
    if dispositivo is None:
        dispositivo = Device(token=datos.token)
        db.add(dispositivo)
    dispositivo.user_id = current_user.id
    dispositivo.platform = datos.platform
    dispositivo.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(dispositivo)
    return dispositivo


@router.delete("/dispositivos/{token}", status_code=204)
def eliminar(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Elimina el celular al cerrar sesion: deja de recibir notificaciones.

    Solo se borra si pertenece al usuario; repetir la peticion no falla.
    """
    db.query(Device).filter(
        Device.token == token, Device.user_id == current_user.id
    ).delete()
    db.commit()
    return Response(status_code=204)
