from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict
from datetime import datetime


class UserBase(BaseModel):
    name: str
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserResponse(UserBase):
    id: int
    created_at: datetime

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


class JobResponse(BaseModel):
    """Entrada del historial de trabajos."""

    id: str
    source_filename: str
    status: str
    stage: Optional[str] = None
    progress: int
    video_type: Optional[str] = None
    project_id: Optional[int] = None
    duration_seconds: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime
    artifacts: Dict[str, bool] = {}

    class Config:
        from_attributes = True
