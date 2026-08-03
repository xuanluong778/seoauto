#!/usr/bin/env bash
# Zero-downtime restart for digiseo (FastAPI on 127.0.0.1:8899).
# Tránh 502 Bad Gateway khi nginx proxy trong lúc uvicorn khởi động (~15–20s).
set -euo pipefail

PRIMARY_PORT=8899
TEMP_PORT=8900
HEALTH_PATH="/health"
SERVICE="digiseo.service"
ROOT="/var/www/seoauto_vn_usr4940/data/www/seoauto.vn"
UVICORN="$ROOT/.venv/bin/uvicorn"
UPSTREAM_FILE="/etc/nginx/fastpanel2-sites/seoauto_vn_usr4940/digiseo-upstream.inc"
TEMP_PID_FILE="/run/digiseo-temp-${TEMP_PORT}.pid"
TEMP_LOG="/var/www/seoauto_vn_usr4940/data/logs/digiseo-temp-${TEMP_PORT}.log"

health_ok() {
    local port="$1"
    curl -sf --max-time 3 -H "Host: seoauto.vn" "http://127.0.0.1:${port}${HEALTH_PATH}" >/dev/null 2>&1 \
        || curl -sf --max-time 3 "http://127.0.0.1:${port}${HEALTH_PATH}" >/dev/null 2>&1
}

write_upstream() {
    local port="$1"
    cat >"$UPSTREAM_FILE" <<EOF
upstream seoauto.vn62 {
    server 127.0.0.1:${port};
    keepalive 16;
}
EOF
    nginx -t
    systemctl reload nginx
}

wait_health() {
    local port="$1"
    local label="$2"
    for i in $(seq 1 90); do
        if health_ok "$port"; then
            echo "[digiseo] ${label} ready after ${i}s (port ${port})"
            return 0
        fi
        sleep 1
    done
    echo "[digiseo] ERROR: ${label} not ready on port ${port} after 90s" >&2
    return 1
}

cleanup_temp() {
    if [[ -f "$TEMP_PID_FILE" ]]; then
        local pid
        pid="$(cat "$TEMP_PID_FILE" 2>/dev/null || true)"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
            sleep 1
            kill -9 "${pid}" 2>/dev/null || true
        fi
        rm -f "$TEMP_PID_FILE"
    fi
}

if [[ "${1:-}" == "--simple" ]]; then
    echo "[digiseo] --simple deprecated; using zero-downtime restart to avoid 502"
fi

if [[ "${1:-}" == "--simple" ]] && health_ok "$PRIMARY_PORT"; then
    : # fall through to zero-downtime below
elif [[ "${1:-}" == "--simple" ]]; then
    systemctl restart "$SERVICE"
    wait_health "$PRIMARY_PORT" "simple restart"
    exit 0
fi

# Primary down — normal restart
if ! health_ok "$PRIMARY_PORT"; then
    echo "[digiseo] primary down — starting ${SERVICE}"
    systemctl restart "$SERVICE"
    wait_health "$PRIMARY_PORT" "cold start"
    exit 0
fi

echo "[digiseo] zero-downtime restart…"
mkdir -p "$(dirname "$TEMP_LOG")"
touch "$TEMP_LOG"
chown seoauto_vn_usr4940:seoauto_vn_usr4940 "$TEMP_LOG" 2>/dev/null || true

# Temp instance on alternate port
sudo -u seoauto_vn_usr4940 env \
    PYTHONPATH="$ROOT" \
    PYTHONUNBUFFERED=1 \
    BENCH_FAST=0 \
    "$UVICORN" main:app --host 127.0.0.1 --port "$TEMP_PORT" --workers 1 \
    >>"$TEMP_LOG" 2>&1 &
TEMP_PID=$!
echo "$TEMP_PID" >"$TEMP_PID_FILE"
trap cleanup_temp EXIT

wait_health "$TEMP_PORT" "temp uvicorn"

write_upstream "$TEMP_PORT"
echo "[digiseo] nginx → port ${TEMP_PORT}"

systemctl restart "$SERVICE"
wait_health "$PRIMARY_PORT" "primary uvicorn"

write_upstream "$PRIMARY_PORT"
echo "[digiseo] nginx → port ${PRIMARY_PORT}"
cleanup_temp
trap - EXIT

echo "[digiseo] zero-downtime restart complete"
