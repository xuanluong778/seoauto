#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/var/www/seoauto_vn_usr4940/data/www/seoauto.vn"
PORT_FILE="$APP_DIR/data/digiseo.active_port"
DEFAULT_PORT=8899

if [[ -f "$PORT_FILE" ]]; then
    PORT="$(tr -d '[:space:]' < "$PORT_FILE")"
else
    PORT="$DEFAULT_PORT"
fi

if [[ ! "$PORT" =~ ^[0-9]+$ ]]; then
    PORT="$DEFAULT_PORT"
fi

cd "$APP_DIR"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$APP_DIR"
export BENCH_FAST=0

exec "$APP_DIR/.venv/bin/uvicorn" main:app --host 127.0.0.1 --port "$PORT" --workers 1
