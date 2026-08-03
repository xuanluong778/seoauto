#!/usr/bin/env bash
# Sync code from dev workspace → production (digiseo.service).
# Dev:  /var/www/seoauto_vn_usr/data/www
# Prod: /var/www/seoauto_vn_usr4940/data/www/seoauto.vn
#
# Usage:
#   ./scripts/deploy_to_production.sh              # full code + templates + static, safe restart
#   ./scripts/deploy_to_production.sh --static     # templates/static only (no restart)
#   ./scripts/deploy_to_production.sh --code       # app/ + main.py only, safe restart
#   ./scripts/deploy_to_production.sh --restart    # systemctl restart (simple, brief downtime)
#   ./scripts/deploy_to_production.sh --no-restart # sync only
#   ./scripts/deploy_to_production.sh --dry-run    # show rsync plan, no changes
set -euo pipefail

DEV_ROOT="${DEV_ROOT:-/var/www/seoauto_vn_usr/data/www}"
PROD_ROOT="${PROD_ROOT:-/var/www/seoauto_vn_usr4940/data/www/seoauto.vn}"
PROD_USER="${PROD_USER:-seoauto_vn_usr4940}"
PROD_GROUP="${PROD_GROUP:-seoauto_vn_usr4940}"
BACKUP_DIR="${BACKUP_DIR:-/var/www/seoauto_vn_usr4940/backups/deploy}"
STAMP="$(date +%Y%m%d_%H%M%S)"

MODE="full"
RESTART_MODE="safe" # safe | simple | none
DRY_RUN=0

RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.pytest_cache/'
  --exclude='env.local'
  --exclude='.env'
  --exclude='app.db'
  --exclude='app.db.*'
  --exclude='data/'
  --exclude='_backup_*/'
  --exclude='running'
)

log() { echo "[deploy] $*"; }
die() { echo "[deploy] ERROR: $*" >&2; exit 1; }

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --static) MODE="static"; RESTART_MODE="none" ;;
    --code) MODE="code" ;;
    --full) MODE="full" ;;
    --safe) RESTART_MODE="safe" ;;
    --restart) RESTART_MODE="simple" ;;
    --no-restart) RESTART_MODE="none" ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
  shift
done

[[ -d "$DEV_ROOT" ]] || die "Dev root missing: $DEV_ROOT"
[[ -d "$PROD_ROOT" ]] || die "Prod root missing: $PROD_ROOT"

rsync_run() {
  local src="$1"
  local dst="$2"
  shift 2
  local flags=(-a --delete "${RSYNC_EXCLUDES[@]}" "$@")
  if [[ "$DRY_RUN" -eq 1 ]]; then
    flags+=(--dry-run --itemize-changes)
  fi
  log "rsync ${src} → ${dst}"
  rsync "${flags[@]}" "$src" "$dst"
}

chown_tree() {
  local path="$1"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  chown -R "${PROD_USER}:${PROD_GROUP}" "$path"
}

backup_slice() {
  local label="$1"
  shift
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  mkdir -p "$BACKUP_DIR"
  local archive="${BACKUP_DIR}/${label}_${STAMP}.tar.gz"
  log "Backup → $archive"
  tar czf "$archive" -C "$PROD_ROOT" "$@" 2>/dev/null || true
  echo "$archive"
}

deploy_static() {
  backup_slice "pre_static" templates static
  rsync_run "$DEV_ROOT/templates/" "$PROD_ROOT/templates/"
  rsync_run "$DEV_ROOT/static/" "$PROD_ROOT/static/"
  chown_tree "$PROD_ROOT/templates"
  chown_tree "$PROD_ROOT/static"
}

deploy_code() {
  backup_slice "pre_code" app main.py
  rsync_run "$DEV_ROOT/app/" "$PROD_ROOT/app/"
  rsync_run "$DEV_ROOT/main.py" "$PROD_ROOT/main.py"
  chown_tree "$PROD_ROOT/app"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    chown "${PROD_USER}:${PROD_GROUP}" "$PROD_ROOT/main.py"
  fi
}

deploy_tests() {
  if [[ -d "$DEV_ROOT/tests" ]]; then
    rsync_run "$DEV_ROOT/tests/" "$PROD_ROOT/tests/"
    chown_tree "$PROD_ROOT/tests"
  fi
}

deploy_scripts() {
  local deploy_scripts=(
    deploy_to_production.sh
    setup_prod_symlinks.sh
    deploy_static.sh
    deploy_digiseo_safe.sh
    restart_digiseo_safe.sh
  )
  for name in "${deploy_scripts[@]}"; do
    if [[ -f "$DEV_ROOT/scripts/$name" ]]; then
      if [[ "$DRY_RUN" -eq 1 ]]; then
        log "would install scripts/$name"
      else
        install -D -m 0755 "$DEV_ROOT/scripts/$name" "$PROD_ROOT/scripts/$name"
        chown "${PROD_USER}:${PROD_GROUP}" "$PROD_ROOT/scripts/$name"
      fi
    fi
  done
}

restart_service() {
  case "$RESTART_MODE" in
    none)
      log "Skip restart (--static or --no-restart)"
      ;;
    safe)
      log "Zero-downtime reload via deploy_digiseo_safe.sh"
      bash "$DEV_ROOT/scripts/deploy_digiseo_safe.sh"
      ;;
    simple)
      log "Simple restart: systemctl restart digiseo.service"
      systemctl restart digiseo.service
      sleep 3
      systemctl is-active --quiet digiseo.service || die "digiseo.service failed after restart"
      ;;
  esac
}

log "Dev:  $DEV_ROOT"
log "Prod: $PROD_ROOT"
log "Mode: $MODE | Restart: $RESTART_MODE | Dry-run: $DRY_RUN"

case "$MODE" in
  static)
    deploy_static
    ;;
  code)
    deploy_code
    deploy_scripts
    restart_service
    ;;
  full)
    deploy_static
    deploy_code
    deploy_tests
    deploy_scripts
    restart_service
    ;;
esac

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "Dry-run complete — no files changed"
else
  log "Deploy complete ($MODE)"
  log "Tip: use ./scripts/setup_prod_symlinks.sh --enable for live template/static sync without deploy"
fi
