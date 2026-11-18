#!/usr/bin/env bash
# Despliegue automático: si la rama main tiene cambios, respalda la base de
# datos, actualiza el código, instala las dependencias que cambiaron y
# reinicia los servicios. Lo ejecuta despliegue.timer cada 5 minutos; también
# se puede ejecutar a mano: bash deploy/desplegar.sh
set -euo pipefail

APP=/opt/karaoke/final_backend_project
RESPALDOS=/opt/karaoke/respaldos
cd "$APP"

git fetch --quiet origin main
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
    exit 0
fi
echo "Desplegando $(git rev-parse --short origin/main)"

# 1. Respaldo de la base de datos (se conservan los 7 más recientes)
set -a; . ./.env; set +a
mkdir -p "$RESPALDOS"
PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -F c \
    -f "$RESPALDOS/${DB_NAME}_$(date +%Y%m%d_%H%M%S).dump" "$DB_NAME"
ls -1t "$RESPALDOS"/*.dump | tail -n +8 | xargs -r rm --

# 2. Código de la rama main (solo avance rápido: el servidor no tiene cambios propios)
git merge --ff-only --quiet origin/main

# 3. Dependencias, solo si cambiaron
if ! sha256sum --check --status .requisitos_instalados 2>/dev/null; then
    venv/bin/pip install -r requirements.txt
    venv_torch/bin/pip install -r requirements-torch.txt
    sha256sum requirements.txt requirements-torch.txt > .requisitos_instalados
fi

# 4. Reinicio: las migraciones se aplican al iniciar la API; los trabajos en
# cola se retoman y el que estaba en proceso se marca con error (RF-03)
sudo systemctl restart api.service trabajador-cola.service
for i in $(seq 1 30); do
    if curl -fs http://127.0.0.1:8000/ >/dev/null; then
        echo "Despliegue correcto"
        exit 0
    fi
    sleep 2
done
echo "La API no respondió después del despliegue"
exit 1
