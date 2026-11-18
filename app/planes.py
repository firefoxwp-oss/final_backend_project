"""Plan freemium: canciones que le quedan en el mes a un usuario."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import LIMITE_PLAN_GRATUITO, Job, User

# Los trabajos cancelados o con error no consumen el cupo del mes
_SIN_CUPO = ("cancelled", "error")

MENSAJE_LIMITE = (
    f"Alcanzaste el límite del plan Gratuito: {LIMITE_PLAN_GRATUITO} "
    "canciones al mes. Pásate al plan Premium para procesar más canciones."
)


def canciones_restantes(db: Session, usuario: User) -> Optional[int]:
    """Canciones que el usuario aún puede procesar este mes.

    Devuelve None si su plan no tiene límite (Premium).
    """
    if usuario.plan != "gratuito":
        return None
    inicio_mes = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    usadas = (
        db.query(Job)
        .filter(
            Job.user_id == usuario.id,
            Job.created_at >= inicio_mes,
            Job.status.notin_(_SIN_CUPO),
        )
        .count()
    )
    return max(0, LIMITE_PLAN_GRATUITO - usadas)
