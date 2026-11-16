"""Migracion ligera de esquema.

`Base.metadata.create_all()` solo crea tablas nuevas: nunca anade columnas a las
que ya existen. Esto aplica los cambios incrementales que necesita el proyecto
sin dependencias adicionales.
"""

from sqlalchemy import inspect, text

# (tabla, columna, DDL)
_COLUMNAS = [
    ("media", "job_id", "ALTER TABLE media ADD COLUMN job_id VARCHAR"),
    ("media", "user_id", "ALTER TABLE media ADD COLUMN user_id INTEGER REFERENCES users(id)"),
    ("media", "project_id", "ALTER TABLE media ADD COLUMN project_id INTEGER REFERENCES proyecto(id)"),
]

_INDICES = [
    ("media", "ix_media_job_id", "CREATE INDEX ix_media_job_id ON media (job_id)"),
    ("media", "ix_media_user_id", "CREATE INDEX ix_media_user_id ON media (user_id)"),
]

# Fechas sin zona horaria: el frontend las interpretaba como hora local.
_TIMESTAMPS = [
    ("media", "created_at"),
    ("users", "created_at"),
    ("proyecto", "created_at"),
]


def aplicar_migraciones(engine) -> None:
    inspector = inspect(engine)
    tablas = set(inspector.get_table_names())

    with engine.begin() as conn:
        for tabla, columna, ddl in _COLUMNAS:
            if tabla not in tablas:
                continue
            existentes = {c["name"] for c in inspector.get_columns(tabla)}
            if columna not in existentes:
                conn.execute(text(ddl))
                print(f"[migracion] {tabla}.{columna} anadida")

        for tabla, indice, ddl in _INDICES:
            if tabla not in tablas:
                continue
            nombres = {i["name"] for i in inspector.get_indexes(tabla)}
            if indice not in nombres:
                conn.execute(text(ddl))
                print(f"[migracion] indice {indice} creado")

        for tabla, columna in _TIMESTAMPS:
            if tabla not in tablas:
                continue
            for col in inspector.get_columns(tabla):
                if col["name"] != columna:
                    continue
                if not getattr(col["type"], "timezone", False):
                    conn.execute(
                        text(
                            f"ALTER TABLE {tabla} ALTER COLUMN {columna} "
                            f"TYPE TIMESTAMPTZ USING {columna} AT TIME ZONE 'UTC'"
                        )
                    )
                    print(f"[migracion] {tabla}.{columna} -> TIMESTAMPTZ")
