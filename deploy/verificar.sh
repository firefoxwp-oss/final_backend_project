#!/usr/bin/env bash
# Verificación periódica del estado (RF-01): si la API no responde, la
# reinicia; si el trabajador de la cola está detenido, lo vuelve a iniciar.
# Lo ejecuta verificacion.timer cada 2 minutos; el resultado queda en el
# registro del sistema (journalctl -u verificacion).
set -uo pipefail
if ! curl -fs --max-time 10 http://127.0.0.1:8000/ >/dev/null; then
    echo "La API no responde: se reinicia"
    sudo systemctl restart api.service
fi
if ! systemctl is-active --quiet trabajador-cola.service; then
    echo "El trabajador de la cola está detenido: se inicia"
    sudo systemctl start trabajador-cola.service
fi
