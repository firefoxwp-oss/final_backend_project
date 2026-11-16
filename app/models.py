from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    CheckConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


def _utcnow():
    return datetime.now(timezone.utc)


# Valores permitidos (los mismos que las restricciones CHECK de la base
# de datos)
ESTADOS_JOB = ("queued", "running", "done", "error", "cancelled")
TIPOS_VIDEO = ("karaoke", "instrumental")
MODELOS_SEPARACION = ("demucs", "spleeter")
TIPOS_MEDIA = (
    "audio",
    "video",
    "audio_vocals",
    "audio_instrumental",
    "video_instrumental",
    "subtitle",
    "video_karaoke",
)
PLATAFORMAS = ("android",)


def _en(columna: str, valores) -> str:
    return f"{columna} IN ({', '.join(repr(v) for v in valores)})"


class Media(Base):
    """Cada archivo generado durante un procesamiento.

    Depende solo del trabajo que lo genero (3FN): el usuario y el proyecto se
    obtienen a traves de `jobs`.
    """

    __tablename__ = "media"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(
        String(36),
        ForeignKey("jobs.id", ondelete="CASCADE", name="fk_media_job"),
        index=True,
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    path = Column(String(500), nullable=False)
    format = Column(String(10), nullable=False)
    type = Column(String(25), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(_en("type", TIPOS_MEDIA), name="ck_media_type"),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    projects = relationship(
        "Project", back_populates="user", cascade="all, delete"
    )


class Project(Base):
    __tablename__ = "proyecto"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    user = relationship("User", back_populates="projects")


class Job(Base):
    """Trabajo de procesamiento: tambien es la cola de trabajos.

    Un trabajo entra en estado `queued` y el trabajador lo toma por orden de
    llegada (`created_at`).
    """

    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE", name="fk_jobs_user"),
        index=True,
        nullable=False,
    )
    project_id = Column(
        Integer,
        ForeignKey("proyecto.id", ondelete="SET NULL", name="fk_jobs_project"),
        index=True,
        nullable=True,
    )
    source_filename = Column(String(255), nullable=False)
    status = Column(
        String(10), nullable=False, default="queued", server_default="queued"
    )
    stage = Column(String(30), nullable=True)
    progress = Column(Integer, nullable=False, default=0, server_default="0")
    video_type = Column(String(12), nullable=True)
    separation_model = Column(String(10), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    # Envio de la notificacion de finalizacion (Pb-4)
    notified_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(_en("status", ESTADOS_JOB), name="ck_jobs_status"),
        CheckConstraint(
            _en("video_type", TIPOS_VIDEO), name="ck_jobs_video_type"
        ),
        CheckConstraint(
            _en("separation_model", MODELOS_SEPARACION),
            name="ck_jobs_separation_model",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_jobs_progress"),
    )


class Device(Base):
    """Celular donde el usuario inicio sesion, para enviarle notificaciones.

    Cada celular se identifica por su token de Firebase Cloud Messaging; si
    otro usuario inicia sesion en el mismo celular, el token pasa a ser suyo.
    """

    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE", name="fk_devices_user"),
        nullable=False,
    )
    token = Column(String(255), nullable=False)
    platform = Column(
        String(10), nullable=False, default="android", server_default="android"
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_devices"),
        UniqueConstraint("token", name="uq_devices_token"),
        CheckConstraint(
            _en("platform", PLATAFORMAS), name="ck_devices_platform"
        ),
    )


Index("ix_jobs_user_created", Job.user_id, Job.created_at)
Index("ix_jobs_queue", Job.status, Job.created_at)
Index("ix_devices_user_id", Device.user_id)
