"""Migracion ligera de esquema.

`Base.metadata.create_all()` solo crea tablas nuevas: nunca anade columnas a
las que ya existen. Esto aplica los cambios incrementales que necesita el
proyecto sin dependencias adicionales. Cada paso comprueba el estado actual,
de modo que la migracion puede ejecutarse en cada arranque sin repetir
cambios.
"""

from sqlalchemy import inspect, text

# (tabla, columna, DDL)
_COLUMNAS = [
    ("media", "job_id", "ALTER TABLE media ADD COLUMN job_id VARCHAR"),
    # Sprint 1: cola de trabajos y modelo de separacion utilizado
    (
        "jobs",
        "separation_model",
        "ALTER TABLE jobs ADD COLUMN separation_model VARCHAR(10)",
    ),
    (
        "jobs",
        "started_at",
        "ALTER TABLE jobs ADD COLUMN started_at TIMESTAMPTZ",
    ),
    # Sprint 2: envio de la notificacion de finalizacion
    (
        "jobs",
        "notified_at",
        "ALTER TABLE jobs ADD COLUMN notified_at TIMESTAMPTZ",
    ),
]

_INDICES = [
    (
        "media",
        "ix_media_job_id",
        "CREATE INDEX ix_media_job_id ON media (job_id)",
    ),
    # Sprint 1: el trabajador toma el siguiente trabajo por estado y antiguedad
    (
        "jobs",
        "ix_jobs_queue",
        "CREATE INDEX ix_jobs_queue ON jobs (status, created_at)",
    ),
]

# Fechas sin zona horaria: el frontend las interpretaba como hora local.
_TIMESTAMPS = [
    ("media", "created_at"),
    ("users", "created_at"),
    ("proyecto", "created_at"),
]

# ------------------------------------------------------------------ Sprint 1
# Diseno fisico del Sprint 1: tipos, nulos, valores por defecto y
# restricciones.

# media pasa a 3FN: el usuario y el proyecto se obtienen a traves de jobs.
_COLUMNAS_ELIMINADAS = [
    ("media", "user_id"),
    ("media", "project_id"),
]

# (tabla, columna, tipo)
_TIPOS = [
    ("users", "name", "VARCHAR(120)"),
    ("users", "email", "VARCHAR(255)"),
    ("users", "password", "VARCHAR(255)"),
    ("proyecto", "name", "VARCHAR(255)"),
    ("proyecto", "description", "TEXT"),
    ("jobs", "id", "VARCHAR(36)"),
    ("jobs", "source_filename", "VARCHAR(255)"),
    ("jobs", "status", "VARCHAR(10)"),
    ("jobs", "stage", "VARCHAR(30)"),
    ("jobs", "video_type", "VARCHAR(12)"),
    ("jobs", "error", "TEXT"),
    ("media", "job_id", "VARCHAR(36)"),
    ("media", "name", "VARCHAR(255)"),
    ("media", "path", "VARCHAR(500)"),
    ("media", "format", "VARCHAR(10)"),
    ("media", "type", "VARCHAR(25)"),
]

# (tabla, columna, valor por defecto o None)
_NO_NULOS = [
    ("users", "created_at", "now()"),
    ("proyecto", "created_at", "now()"),
    ("jobs", "created_at", "now()"),
    ("media", "created_at", "now()"),
    ("media", "job_id", None),
]

_DEFAULTS = [
    ("jobs", "status", "'queued'"),
    ("jobs", "progress", "0"),
]

_CHECKS = [
    (
        "jobs",
        "ck_jobs_status",
        "CHECK (status IN ('queued', 'running', 'done', 'error', "
        "'cancelled'))",
    ),
    (
        "jobs",
        "ck_jobs_video_type",
        "CHECK (video_type IN ('karaoke', 'instrumental'))",
    ),
    (
        "jobs",
        "ck_jobs_separation_model",
        "CHECK (separation_model IN ('demucs', 'spleeter'))",
    ),
    ("jobs", "ck_jobs_progress", "CHECK (progress BETWEEN 0 AND 100)"),
    (
        "media",
        "ck_media_type",
        "CHECK (type IN ('audio', 'video', 'audio_vocals', "
        "'audio_instrumental', "
        "'video_instrumental', 'subtitle', 'video_karaoke'))",
    ),
]

# (tabla, nombre, columna, referencia, nombres antiguos que reemplaza)
_FOREIGN_KEYS = [
    (
        "jobs",
        "fk_jobs_user",
        "user_id",
        "REFERENCES users (id) ON DELETE CASCADE",
        ["jobs_user_id_fkey"],
    ),
    (
        "jobs",
        "fk_jobs_project",
        "project_id",
        "REFERENCES proyecto (id) ON DELETE SET NULL",
        ["jobs_project_id_fkey"],
    ),
    (
        "media",
        "fk_media_job",
        "job_id",
        "REFERENCES jobs (id) ON DELETE CASCADE",
        [],
    ),
]


def _columnas(conn, tabla):
    return {c["name"]: c for c in inspect(conn).get_columns(tabla)}


def _aplicar_sprint1(conn, tablas) -> None:
    if not {"users", "proyecto", "jobs", "media"} <= tablas:
        return

    # Archivos sin trabajo (anteriores a la tabla jobs): ningun servicio puede
    # acceder a ellos y impiden la llave foranea. Solo se borra su registro.
    huerfanos = conn.execute(
        text(
            "DELETE FROM media WHERE job_id IS NULL "
            "OR job_id NOT IN (SELECT id FROM jobs)"
        )
    ).rowcount
    if huerfanos:
        print(
            f"[migracion] {huerfanos} registros de media sin trabajo "
            "eliminados"
        )

    for tabla, columna in _COLUMNAS_ELIMINADAS:
        if columna in _columnas(conn, tabla):
            conn.execute(text(f"ALTER TABLE {tabla} DROP COLUMN {columna}"))
            print(f"[migracion] {tabla}.{columna} eliminada")

    for tabla, columna, tipo in _TIPOS:
        col = _columnas(conn, tabla).get(columna)
        if col is not None and str(col["type"]).upper() != tipo:
            conn.execute(
                text(f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE {tipo}")
            )
            print(f"[migracion] {tabla}.{columna} -> {tipo}")

    for tabla, columna, defecto in _NO_NULOS:
        col = _columnas(conn, tabla).get(columna)
        if col is None:
            continue
        if defecto and col["default"] is None:
            conn.execute(
                text(
                    f"ALTER TABLE {tabla} ALTER COLUMN {columna} "
                    f"SET DEFAULT {defecto}"
                )
            )
        if col["nullable"]:
            if defecto:
                conn.execute(
                    text(
                        f"UPDATE {tabla} SET {columna} = {defecto} "
                        f"WHERE {columna} IS NULL"
                    )
                )
            conn.execute(
                text(
                    f"ALTER TABLE {tabla} ALTER COLUMN {columna} SET NOT NULL"
                )
            )
            print(f"[migracion] {tabla}.{columna} NOT NULL")

    for tabla, columna, defecto in _DEFAULTS:
        col = _columnas(conn, tabla).get(columna)
        if col is not None and col["default"] is None:
            conn.execute(
                text(
                    f"ALTER TABLE {tabla} ALTER COLUMN {columna} "
                    f"SET DEFAULT {defecto}"
                )
            )
            print(f"[migracion] {tabla}.{columna} DEFAULT {defecto}")

    for tabla, nombre, ddl in _CHECKS:
        existentes = {
            c["name"] for c in inspect(conn).get_check_constraints(tabla)
        }
        if nombre not in existentes:
            conn.execute(
                text(f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} {ddl}")
            )
            print(f"[migracion] restriccion {nombre} creada")

    for tabla, nombre, columna, referencia, antiguos in _FOREIGN_KEYS:
        existentes = {f["name"] for f in inspect(conn).get_foreign_keys(tabla)}
        if nombre in existentes:
            continue
        for antiguo in antiguos:
            if antiguo in existentes:
                conn.execute(
                    text(f"ALTER TABLE {tabla} DROP CONSTRAINT {antiguo}")
                )
        conn.execute(
            text(
                f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} "
                f"FOREIGN KEY ({columna}) {referencia}"
            )
        )
        print(f"[migracion] llave foranea {nombre} creada")


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
                            f"TYPE TIMESTAMPTZ USING {columna} "
                            "AT TIME ZONE 'UTC'"
                        )
                    )
                    print(f"[migracion] {tabla}.{columna} -> TIMESTAMPTZ")

        _aplicar_sprint1(conn, tablas)
