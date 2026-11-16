import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.persistencia.database import engine
from app.persistencia.migrate import aplicar_migraciones
from app.persistencia.models import Base
from app.api import rutas_autenticacion, rutas_proyectos, rutas_trabajos
from app.karaoke.karaoke import karaoke_router

Base.metadata.create_all(bind=engine)
aplicar_migraciones(engine)

app = FastAPI()

# Origenes permitidos: configurables por entorno para poder desplegar.
_origins_env = os.getenv("FRONTEND_ORIGIN", "")
origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Job-ID",
        "X-Video-Type",
        "X-Archivos-Generados",
        "X-Karaoke-Error",
        "Content-Disposition",
    ],
)

app.include_router(karaoke_router)
app.include_router(rutas_autenticacion.router)
app.include_router(rutas_proyectos.router)
app.include_router(rutas_trabajos.router)

# --------------------------------------------------------------------- basico


@app.get("/")
def root():
    return {"message": "Backend running", "docs": "/docs", "redoc": "/redoc"}
