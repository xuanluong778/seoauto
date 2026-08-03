#!/usr/bin/env bash
# Zero-downtime backend reload for seoauto.vn (avoids 502 during ~30s uvicorn cold start).
set -euo pipefail

APP_DIR="/var/www/seoauto_vn_usr4940/data/www/seoauto.vn"
UPSTREAM_INC="/etc/nginx/fastpanel2-sites/seoauto_vn_usr4940/digiseo-upstream.inc"
SYSTEMD_UNIT="/etc/systemd/system/digiseo.service"
PORT_FILE="$APP_DIR/data/digiseo.active_port"
VENV_UVICORN="$APP_DIR/.venv/bin/uvicorn"
RUN_USER="seoauto_vn_usr4940"
PRIMARY_PORT=8899
ALT_PORT=8900
HEALTH_PATH="/health"
MAX_WAIT=90

log() { echo "[deploy_digiseo_safe] $*"; }

current_port() {
    if [[ -f "$PORT_FILE" ]]; then
        tr -d '[:space:]' < "$PORT_FILE"
    else
        echo "$PRIMARY_PORT"
    fi
}

port_in_use() {
    ss -ltn "sport = :$1" 2>/dev/null | grep -q ":$1"
}

wait_healthy() {
    local port="$1"
    local i
    for ((i = 1; i <= MAX_WAIT; i++)); do
        if curl -sf --max-time 2 "http://127.0.0.1:${port}${HEALTH_PATH}" >/dev/null 2>&1; then
            log "Healthy on port ${port} after ${i}s"
            return 0
        fi
        sleep 1
    done
    return 1
}

write_upstream() {
    local port="$1"
    cat > "$UPSTREAM_INC" <<EOF
upstream seoauto.vn62 {
    server 127.0.0.1:${port};
    keepalive 16;
}
EOF
}

stop_port() {
    local port="$1"
    if port_in_use "$port"; then
        log "Stopping process on port ${port}"
        fuser -k "${port}/tcp" >/dev/null 2>&1 || true
        sleep 1
    fi
}

start_standalone() {
    local port="$1"
    log "Starting uvicorn on port ${port}"
    sudo -u "$RUN_USER" bash -c "cd \"$APP_DIR\" && env PYTHONUNBUFFERED=1 PYTHONPATH=\"$APP_DIR\" BENCH_FAST=0 \
        \"$VENV_UVICORN\" main:app --host 127.0.0.1 --port \"$port\" --workers 1 \
        >> \"$APP_DIR/data/logs/digiseo-standalone.log\" 2>&1" &
    echo $!
}

main() {
    local cur new pid
    cur="$(current_port)"
    if [[ "$cur" == "$PRIMARY_PORT" ]]; then
        new="$ALT_PORT"
    else
        new="$PRIMARY_PORT"
    fi

    log "Current port=${cur}, target port=${new}"

    stop_port "$new"
    pid="$(start_standalone "$new")"

    if ! wait_healthy "$new"; then
        log "ERROR: new instance failed to become healthy on port ${new}"
        kill "$pid" 2>/dev/null || true
        stop_port "$new"
        exit 1
    fi

    write_upstream "$new"
    nginx -t
    nginx -s reload
    log "Nginx switched to port ${new}"

    echo "$new" > "$PORT_FILE"
    chown "$RUN_USER:$RUN_USER" "$PORT_FILE"

    systemctl stop digiseo.service 2>/dev/null || true
    stop_port "$cur"

    if grep -q 'scripts/digiseo_start.sh' "$SYSTEMD_UNIT" 2>/dev/null; then
        systemctl daemon-reload
        # Hand off to systemd only after standalone is no longer needed.
        kill "$pid" 2>/dev/null || true
        stop_port "$new"
        sleep 1
        systemctl start digiseo.service
        if ! wait_healthy "$new"; then
            log "ERROR: systemd instance failed on port ${new}; restarting standalone"
            pid="$(start_standalone "$new")"
            if ! wait_healthy "$new"; then
                kill "$pid" 2>/dev/null || true
                exit 1
            fi
            exit 1
        fi
        log "Systemd instance active on port ${new}"
    else
        log "Standalone serving on port ${new} (pid ${pid})"
    fi

    log "Deploy complete — serving on port ${new}"
}

main "$@"
