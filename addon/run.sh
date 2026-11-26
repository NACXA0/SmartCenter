#!/usr/bin/with-contenv bashio
set -euo pipefail

export SMARTCENTER_OPTIONS="$(bashio::addon.options)"
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"

# 官方 Mosquitto 插件（config.yaml services: mqtt:need）
if bashio::services.available "mqtt"; then
  export MQTT_HOST="$(bashio::services mqtt 'host')"
  export MQTT_PORT="$(bashio::services mqtt 'port')"
  export MQTT_USER="$(bashio::services mqtt 'username')"
  export MQTT_PASSWORD="$(bashio::services mqtt 'password')"
  bashio::log.info "MQTT via supervisor → ${MQTT_HOST}:${MQTT_PORT}"
else
  bashio::log.warning "MQTT service not available; set mqtt options or install Mosquitto"
fi

exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080
