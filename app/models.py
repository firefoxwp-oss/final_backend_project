from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Media(Base):
    """Cada archivo generado durante un procesamiento."""

    __tablename__ = "media"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    format = Column(String, nullable=False)
    type = Column(String, nullable=False)
    # Vinculo con el trabajo, el usuario y el proyecto (antes la tabla estaba suelta)
    job_id = Column(String, index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    project_id = Column(Integer, ForeignKey("proyecto.id"), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    projects = relationship("Project", back_populates="user", cascade="all, delete")


class Project(Base):
    __tablename__ = "proyecto"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="projects")


class Job(Base):
    """Trabajo de procesamiento: estado, progreso e historial."""

    __tablename__ = "jobs"

    id = Column(String, primary_key=True)  # UUID de sesion
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    project_id = Column(Integer, ForeignKey("proyecto.id"), index=True, nullable=True)
    source_filename = Column(String, nullable=False)
    status = Column(String, nullable=False, default="running")  # running|done|error
    stage = Column(String, nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    video_type = Column(String, nullable=True)  # karaoke|instrumental
    duration_seconds = Column(Integer, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)


Index("ix_jobs_user_created", Job.user_id, Job.created_at)
