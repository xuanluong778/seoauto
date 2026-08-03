#!/usr/bin/env bash
# Social Auto production scheduler — gọi API nội bộ (Facebook + Web 2.0).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

_load_env_var() {
  local key="$1"
  local file="env.local"
  [[ -f "$file" ]] || return 0
  local line val
  line=$(grep -E "^${key}=" "$file" | tail -1) || return 0
  val="${line#*=}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  export "${key}=${val}"
}

for _k in DIGISEO_PORT SOCIAL_AUTO_SCHEDULER_URL SOCIAL_AUTO_SCHEDULER_LIMIT WEB20_INTERNAL_TOKEN INTERNAL_CRON_TOKEN; do
  _load_env_var "$_k"
done

PORT="${DIGISEO_PORT:-8899}"
BASE="${SOCIAL_AUTO_SCHEDULER_URL:-http://127.0.0.1:${PORT}/api/social/scheduler/run}"
TOKEN="${WEB20_INTERNAL_TOKEN:-${INTERNAL_CRON_TOKEN:-}}"

if [[ -z "$TOKEN" ]]; then
  echo "[social-auto-scheduler] ERROR: WEB20_INTERNAL_TOKEN or INTERNAL_CRON_TOKEN not set" >&2
  exit 1
fi

LIMIT="${SOCIAL_AUTO_SCHEDULER_LIMIT:-30}"
HTTP_CODE=$(curl -sS -o /tmp/social_auto_scheduler_out.json -w "%{http_code}" \
  -X POST "${BASE}?limit=${LIMIT}" \
  -H "X-Internal-Token: ${TOKEN}" \
  -H "Accept: application/json" \
  --connect-timeout 10 \
  --max-time 120)

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "[social-auto-scheduler] HTTP ${HTTP_CODE}" >&2
  cat /tmp/social_auto_scheduler_out.json >&2 || true
  exit 1
fi

cat /tmp/social_auto_scheduler_out.json
echo ""
