from pydantic import BaseModel, EmailStr, Field
from typing import Dict, List, Optional
from datetime import datetime


class UserBase(BaseModel):
    name: str
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserResponse(UserBase):
    id: int
    created_at: datetime
    plan: str = "gratuito"
    # Canciones que le quedan en el mes; None si su plan no tiene limite
    canciones_restantes: Optional[int] = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectCreate(ProjectBase):
    user_id: int


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectResponse(ProjectBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class JobStatus(BaseModel):
    """Estado en vivo de un procesamiento."""

    id: str
    status: str
    stage: Optional[str] = None
    progress: int = 0
    video_type: Optional[str] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class TrabajoEncolado(BaseModel):
    """Respuesta de la subida: el trabajo queda en la cola."""

    job_id: str
    status: str


class TrabajoCanceladoRespuesta(BaseModel):
    """Respuesta de la cancelacion de un trabajo."""

    job_id: str
    status: str


class JobResponse(BaseModel):
    """Entrada del historial de trabajos."""

    id: str
    source_filename: str
    status: str
    stage: Optional[str] = None
    progress: int
    video_type: Optional[str] = None
    separation_model: Optional[str] = None
    project_id: Optional[int] = None
    duration_seconds: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    # Posicion en la cola (1 = el siguiente); solo mientras espera
    queue_position: Optional[int] = None
    artifacts: Dict[str, bool] = {}

    class Config:
        from_attributes = True


class PalabraLetra(BaseModel):
    texto: str
    inicio: float
    fin: float


class LineaLetra(BaseModel):
    inicio: float
    fin: float
    palabras: List[PalabraLetra]


class LetraRespuesta(BaseModel):
    """Letra sincronizada por palabra del Modo Karaoke (Pb-5)."""

    lineas: List[LineaLetra]


class DispositivoRegistro(BaseModel):
    """Celular que se registra para recibir notificaciones (Pb-4)."""

    token: str = Field(min_length=1, max_length=255)
    platform: str = "android"


class DispositivoRespuesta(BaseModel):
    id: int
    platform: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
