#!/usr/bin/env bash
# Actualiza el subdominio de DuckDNS con la IP pública actual del servidor,
# que cambia cada vez que la instancia se enciende. Lo ejecuta duckdns.timer.
# El subdominio y el token están en /opt/karaoke/duckdns.env (fuera del repositorio).
set -euo pipefail
. /opt/karaoke/duckdns.env
RESPUESTA=$(curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMINIO}&token=${DUCKDNS_TOKEN}&ip=")
[ "$RESPUESTA" = "OK" ] || { echo "DuckDNS respondió: $RESPUESTA"; exit 1; }
