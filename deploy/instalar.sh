#!/usr/bin/env bash
# Instalación del servidor en Ubuntu Server 22.04 (Amazon EC2): paquetes del
# sistema, PostgreSQL, los dos entornos de Python, los modelos de IA, los
# servicios systemd, DuckDNS, la verificación periódica del estado, el
# despliegue automático, el agente de CloudWatch y Caddy con HTTPS.
#
# Requisitos:
#   - el repositorio clonado en /opt/karaoke/final_backend_project;
#   - su archivo .env completo (ver deploy/env.ejemplo);
#   - /opt/karaoke/duckdns.env con el subdominio y el token (ver deploy/duckdns.ejemplo).
# Uso: bash deploy/instalar.sh
# Se puede volver a ejecutar sin problema: cada paso comprueba si ya se hizo.
set -euo pipefail

APP=/opt/karaoke/final_backend_project
cd "$APP"
[ -f .env ] || { echo "Falta $APP/.env (copia deploy/env.ejemplo y complétalo)"; exit 1; }
[ -f /opt/karaoke/duckdns.env ] || { echo "Falta /opt/karaoke/duckdns.env (ver deploy/duckdns.ejemplo)"; exit 1; }
set -a; . ./.env; . /opt/karaoke/duckdns.env; set +a
for v in DB_USER DB_PASSWORD DB_NAME JWT_SECRET_KEY DUCKDNS_SUBDOMINIO DUCKDNS_TOKEN; do
    [ -n "${!v:-}" ] || { echo "Falta $v"; exit 1; }
done
DOMINIO="$DUCKDNS_SUBDOMINIO.duckdns.org"
chmod 600 .env /opt/karaoke/duckdns.env
chmod +x deploy/*.sh

echo "== 1. Espacio en disco"
LIBRE_GB=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
echo "Libre: ${LIBRE_GB} GB"
[ "$LIBRE_GB" -ge 18 ] || { echo "Se necesitan al menos 18 GB libres"; exit 1; }

echo "== 2. Paquetes del sistema"
sudo apt-get update -y
sudo apt-get install -y python3.10-venv python3-dev build-essential git curl \
    ffmpeg libsndfile1 postgresql postgresql-contrib \
    debian-keyring debian-archive-keyring apt-transport-https gnupg
ffmpeg -hide_banner -filters | grep -q rubberband \
    || { echo "FFmpeg no tiene el filtro rubberband (cambio de tono)"; exit 1; }

echo "== 3. Memoria de intercambio (4 GB) para los modelos de IA"
if ! swapon --show | grep -q /swapfile; then
    sudo fallocate -l 4G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== 4. Base de datos PostgreSQL"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD'"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER"

echo "== 5. Entornos de Python"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
[ -d venv_torch ] || python3 -m venv venv_torch
venv_torch/bin/pip install --upgrade pip
venv_torch/bin/pip install -r requirements-torch.txt
sha256sum requirements.txt requirements-torch.txt > .requisitos_instalados

echo "== 6. Modelos de IA (se cargan sin conexión desde pretrained_models)"
venv_torch/bin/python pretrained_models/descargar_modelos.py

echo "== 7. Servicios del sistema"
mkdir -p media /opt/karaoke/respaldos
for s in api.service trabajador-cola.service despliegue.service despliegue.timer \
         duckdns.service duckdns.timer verificacion.service verificacion.timer; do
    sudo cp "deploy/$s" "/etc/systemd/system/$s"
done
sudo systemctl daemon-reload
sudo systemctl enable --now api.service trabajador-cola.service \
    duckdns.timer verificacion.timer despliegue.timer

echo "== 8. DuckDNS: $DOMINIO apunta a la IP de este servidor"
deploy/duckdns.sh
sleep 60  # tiempo para que el cambio de DNS se propague antes de pedir el certificado

echo "== 9. Agente de CloudWatch (memoria y disco; requiere el rol IAM de la instancia)"
if ! command -v /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl >/dev/null; then
    curl -fsSLo /tmp/cwagent.deb \
        https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
    sudo dpkg -i /tmp/cwagent.deb
fi
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
    -a fetch-config -m ec2 -s -c "file:$APP/deploy/cloudwatch.json"

echo "== 10. Caddy (HTTPS con Let's Encrypt)"
if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list
    sudo apt-get update -y
    sudo apt-get install -y caddy
fi
sed "s/DOMINIO/$DOMINIO/" deploy/Caddyfile | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "== 11. Comprobación"
for i in $(seq 1 30); do
    curl -fs http://127.0.0.1:8000/ >/dev/null && break
    sleep 2
done
curl -fs http://127.0.0.1:8000/ && echo
systemctl --no-pager --lines=0 status api.service trabajador-cola.service caddy \
    amazon-cloudwatch-agent duckdns.timer verificacion.timer despliegue.timer
echo "Listo: https://$DOMINIO/docs"
