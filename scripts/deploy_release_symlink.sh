#!/usr/bin/env bash
# Deploy a NEW release directory from current commit worktree, smoke on ephemeral port, then switch symlink.
set -euo pipefail

WWW_ROOT="/var/www/seoauto_vn_usr/data/www"
CURRENT_LINK="${WWW_ROOT}/seoauto.vn-current"
RELEASES="${WWW_ROOT}/releases"
SHARED="${WWW_ROOT}/shared"
ECOSYSTEM="${SHARED}/ecosystem.config.cjs"
STAMP="$(date +%Y%m%d_%H%M%S)"
NEW_REL="${RELEASES}/seoauto-${STAMP}"
OLD_REL="$(readlink -f "${CURRENT_LINK}")"
SMOKE_PORT="${SMOKE_PORT:-8901}"
LOG_DIR="/var/www/seoauto_vn_usr/data/logs"
mkdir -p "${LOG_DIR}" "${RELEASES}"

log() { echo "[deploy-release] $*"; }
die() { echo "[deploy-release] ERROR: $*" >&2; exit 1; }

[[ -d "${OLD_REL}" ]] || die "current release missing: ${OLD_REL}"

log "OLD=${OLD_REL}"
log "NEW=${NEW_REL}"

# 1) Copy release (code + venv). Keep data from old (runtime JSON residual); env via shared.
rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='data/*.json' \
  --exclude='app.db' \
  "${OLD_REL}/" "${NEW_REL}/"

# Preserve runtime data trees from previous release (no truncate)
if [[ -d "${OLD_REL}/data" ]]; then
  rsync -a "${OLD_REL}/data/" "${NEW_REL}/data/"
fi

# Prefer shared env.local symlink if not present
if [[ ! -e "${NEW_REL}/env.local" && -f "${SHARED}/env.local" ]]; then
  ln -sfn "${SHARED}/env.local" "${NEW_REL}/env.local"
fi

# 2) Apply migration ONCE (as docker superuser when needed for ALTER)
log "Applying credit SaaS gate migration (deploy-time only)"
set -a
# shellcheck disable=SC1091
source "${SHARED}/env.local"
set +a
export PYTHONPATH="${NEW_REL}"
cd "${NEW_REL}"
if ! "${NEW_REL}/.venv/bin/python" -c "from app.migrations.ensure_credit_saas_gate import assert_credit_saas_gate_schema; assert_credit_saas_gate_schema()"; then
  log "Schema incomplete; applying via DB superuser if available"
  docker exec seoauto-postgres psql -U seoauto -d digiseo -v ON_ERROR_STOP=1 <<'SQL' || true
ALTER TABLE credit_ledgers ADD COLUMN IF NOT EXISTS organization_id INTEGER;
ALTER TABLE credit_ledgers ADD COLUMN IF NOT EXISTS feature_code VARCHAR(64);
ALTER TABLE credit_ledgers ADD COLUMN IF NOT EXISTS job_id VARCHAR(128);
ALTER TABLE credit_ledgers ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_ledgers_idempotency ON credit_ledgers (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_credit_ledgers_feature_code ON credit_ledgers (feature_code);
CREATE INDEX IF NOT EXISTS ix_credit_ledgers_job_id ON credit_ledgers (job_id);
SQL
  "${NEW_REL}/.venv/bin/python" -c "from app.migrations.ensure_credit_saas_gate import apply_credit_saas_gate_migration, assert_credit_saas_gate_schema; apply_credit_saas_gate_migration(); assert_credit_saas_gate_schema(); print('migration_assert_ok')"
else
  log "Schema already OK (migration previously applied)"
fi

log "Applying SePay webhook idempotency migration (deploy-time)"
# App role may not own sepay_payment_transactions — use superuser for ALTER when needed
docker exec -i seoauto-postgres psql -U seoauto -d digiseo -v ON_ERROR_STOP=1 <<'SQL' || true
ALTER TABLE sepay_payment_transactions ADD COLUMN IF NOT EXISTS process_status VARCHAR(24);
ALTER TABLE sepay_payment_transactions ADD COLUMN IF NOT EXISTS failure_reason VARCHAR(512);
ALTER TABLE sepay_payment_transactions ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sepay_webhook_events_idempotency
  ON sepay_webhook_events (idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sepay_webhook_events_provider_tx
  ON sepay_webhook_events (provider_transaction_id)
  WHERE provider_transaction_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_sepay_tx_idempotency
  ON sepay_payment_transactions (idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_provider_tx
  ON payment_transactions (provider, provider_transaction_id)
  WHERE provider_transaction_id IS NOT NULL;
SQL
"${NEW_REL}/.venv/bin/python" -c "
from app.migrations.ensure_sepay_webhook_idempotency import apply_sepay_webhook_idempotency_migration, schema_status
print(apply_sepay_webhook_idempotency_migration())
st = schema_status()
assert st.get('ok') and not st.get('missing'), st
print('sepay_webhook_idempotency_ok', st)
" || die "sepay webhook idempotency migration failed"

# 3) Internal smoke on alternate port (does not touch live 8899 yet)
log "Starting smoke uvicorn on :${SMOKE_PORT}"
SMOKE_PID_FILE="${LOG_DIR}/smoke-${STAMP}.pid"
"${NEW_REL}/.venv/bin/uvicorn" main:app --host 127.0.0.1 --port "${SMOKE_PORT}" --workers 1 \
  >"${LOG_DIR}/smoke-${STAMP}.out.log" 2>"${LOG_DIR}/smoke-${STAMP}.err.log" &
echo $! >"${SMOKE_PID_FILE}"
SMOKE_PID="$(cat "${SMOKE_PID_FILE}")"

cleanup_smoke() {
  if kill -0 "${SMOKE_PID}" 2>/dev/null; then
    kill "${SMOKE_PID}" 2>/dev/null || true
    wait "${SMOKE_PID}" 2>/dev/null || true
  fi
}
trap cleanup_smoke EXIT

ok=0
for i in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${SMOKE_PORT}/health" || true)"
  if [[ "${code}" == "200" ]]; then ok=1; break; fi
  sleep 1
done
[[ "${ok}" == "1" ]] || die "smoke health failed (see ${LOG_DIR}/smoke-${STAMP}.err.log)"

for path in / /health /content-ai /pricing /api/saas/plans /api/payments/sepay/webhook; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${SMOKE_PORT}${path}" || true)"
  log "smoke ${code} ${path}"
  [[ "${code}" == "200" ]] || die "smoke path failed ${path}=${code}"
done
for path in /keywords/volume/batch /analyze /api/index-control/submit-indexing; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${SMOKE_PORT}${path}" \
    -H 'Content-Type: application/json' -d '{}' || true)"
  log "smoke-gate ${code} POST ${path}"
  [[ "${code}" == "401" || "${code}" == "403" || "${code}" == "422" ]] || die "unexpected gate ${path}=${code}"
done

cleanup_smoke
trap - EXIT

# 4) Atomic symlink switch + PM2 reload (cwd follows current)
log "Switch symlink ${CURRENT_LINK} -> ${NEW_REL}"
ln -sfn "${NEW_REL}" "${CURRENT_LINK}.tmp"
mv -Tf "${CURRENT_LINK}.tmp" "${CURRENT_LINK}"
readlink -f "${CURRENT_LINK}" | tee "${SHARED}/DEPLOY_META.txt" >/dev/null
{
  echo "commit=$(git -c safe.directory="${NEW_REL}" -C "${NEW_REL}" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "release=$(readlink -f "${CURRENT_LINK}")"
  echo "previous=${OLD_REL}"
  echo "switched_at=$(date -Iseconds)"
} > "${SHARED}/DEPLOY_META.txt"

pm2 startOrReload "${ECOSYSTEM}" --update-env
ok=0
for i in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8899/health || true)"
  if [[ "${code}" == "200" ]]; then ok=1; break; fi
  sleep 1
done
[[ "${ok}" == "1" ]] || die "live health after switch failed"

for path in / /health /content-ai /pricing /account-billing /api/saas/plans; do
  code="$(curl -s -o /dev/null -w '%{http_code}' -L "https://seoauto.vn${path}" || true)"
  log "live ${code} ${path}"
  [[ "${code}" == "200" ]] || die "live path failed ${path}=${code}"
done

log "PASS release=${NEW_REL}"
echo "${NEW_REL}"
