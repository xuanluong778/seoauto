#!/usr/bin/env bash
# Start keyword cluster worker (optional — KEYWORD_CLUSTER_INLINE=1 chạy job trong API).
set -euo pipefail
ROOT="/var/www/seoauto_vn_usr4940/data/www/seoauto.vn"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" scripts/keyword_cluster_worker.py
