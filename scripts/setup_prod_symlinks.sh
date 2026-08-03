#!/usr/bin/env bash
# Point production code paths at the dev workspace (single source of truth).
# Runtime data (.venv, env.local, app.db, data/) stays on production only.
#
# Usage:
#   ./scripts/setup_prod_symlinks.sh --status
#   ./scripts/setup_prod_symlinks.sh --enable          # symlink app, templates, static, main.py
#   ./scripts/setup_prod_symlinks.sh --enable --tests  # also symlink tests/
#   ./scripts/setup_prod_symlinks.sh --disable         # restore from latest backup
set -euo pipefail

DEV_ROOT="${DEV_ROOT:-/var/www/seoauto_vn_usr/data/www}"
PROD_ROOT="${PROD_ROOT:-/var/www/seoauto_vn_usr4940/data/www/seoauto.vn}"
PROD_USER="${PROD_USER:-seoauto_vn_usr4940}"
PROD_GROUP="${PROD_GROUP:-seoauto_vn_usr4940}"
BACKUP_ROOT="${PROD_ROOT}/.deploy-symlink-backups"
STAMP="$(date +%Y%m%d_%H%M%S)"

LINK_PATHS=(app templates static main.py)
INCLUDE_TESTS=0
ACTION=""

log() { echo "[symlink] $*"; }
die() { echo "[symlink] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  setup_prod_symlinks.sh --status
  setup_prod_symlinks.sh --enable [--tests]
  setup_prod_symlinks.sh --disable
EOF
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable) ACTION="enable" ;;
    --disable) ACTION="disable" ;;
    --status) ACTION="status" ;;
    --tests) INCLUDE_TESTS=1 ;;
    -h|--help) usage 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

[[ -n "$ACTION" ]] || usage 1
[[ -d "$DEV_ROOT" ]] || die "Dev root missing: $DEV_ROOT"
[[ -d "$PROD_ROOT" ]] || die "Prod root missing: $PROD_ROOT"

is_symlink_to_dev() {
  local rel="$1"
  local prod_path="$PROD_ROOT/$rel"
  [[ -L "$prod_path" ]] || return 1
  local target
  target="$(readlink -f "$prod_path")"
  local expected
  expected="$(readlink -f "$DEV_ROOT/$rel")"
  [[ "$target" == "$expected" ]]
}

show_status() {
  log "Dev:  $DEV_ROOT"
  log "Prod: $PROD_ROOT"
  local rel
  for rel in "${LINK_PATHS[@]}" tests; do
    local prod_path="$PROD_ROOT/$rel"
    if [[ ! -e "$prod_path" && ! -L "$prod_path" ]]; then
      log "  $rel: (missing)"
    elif is_symlink_to_dev "$rel"; then
      log "  $rel: SYMLINK → $DEV_ROOT/$rel"
    elif [[ -L "$prod_path" ]]; then
      log "  $rel: symlink (other) → $(readlink "$prod_path")"
    else
      log "  $rel: regular copy"
    fi
  done
}

backup_path() {
  local rel="$1"
  local backup="${BACKUP_ROOT}/${STAMP}/${rel}"
  mkdir -p "$(dirname "$backup")"
  if [[ -e "$PROD_ROOT/$rel" || -L "$PROD_ROOT/$rel" ]]; then
    if [[ -d "$PROD_ROOT/$rel" && ! -L "$PROD_ROOT/$rel" ]]; then
      cp -a "$PROD_ROOT/$rel" "$backup"
    elif [[ -f "$PROD_ROOT/$rel" && ! -L "$PROD_ROOT/$rel" ]]; then
      cp -a "$PROD_ROOT/$rel" "$backup"
    elif [[ -L "$PROD_ROOT/$rel" ]]; then
      cp -a "$PROD_ROOT/$rel" "${backup}.link"
    fi
  fi
}

enable_symlink() {
  local rel="$1"
  local prod_path="$PROD_ROOT/$rel"
  local dev_path="$DEV_ROOT/$rel"

  [[ -e "$dev_path" || -L "$dev_path" ]] || die "Dev path missing: $dev_path"

  if is_symlink_to_dev "$rel"; then
    log "$rel already symlinked"
    return 0
  fi

  backup_path "$rel"
  rm -rf "$prod_path"
  ln -s "$dev_path" "$prod_path"
  log "linked $rel → $dev_path"
}

disable_symlinks() {
  local latest
  latest="$(ls -1dt "$BACKUP_ROOT"/*/ 2>/dev/null | head -1 || true)"
  [[ -n "$latest" ]] || die "No backup found under $BACKUP_ROOT"

  log "Restoring from $latest"
  local rel
  for rel in app templates static main.py tests; do
    local prod_path="$PROD_ROOT/$rel"
    local backup="${latest%/}/$rel"
    local backup_link="${latest%/}/${rel}.link"

    if [[ -d "$backup" || -f "$backup" ]]; then
      rm -rf "$prod_path"
      cp -a "$backup" "$prod_path"
      log "restored $rel"
    elif [[ -f "$backup_link" ]]; then
      rm -rf "$prod_path"
      cp -a "$backup_link" "$prod_path"
      log "restored $rel (symlink copy)"
    fi
  done
}

case "$ACTION" in
  status)
    show_status
    ;;
  enable)
    mkdir -p "$BACKUP_ROOT/$STAMP"
    log "Backup snapshot: $BACKUP_ROOT/$STAMP"
    for rel in "${LINK_PATHS[@]}"; do
      enable_symlink "$rel"
    done
    if [[ "$INCLUDE_TESTS" -eq 1 && -d "$DEV_ROOT/tests" ]]; then
      enable_symlink "tests"
    fi
    chown -h "${PROD_USER}:${PROD_GROUP}" \
      "$PROD_ROOT/app" \
      "$PROD_ROOT/templates" \
      "$PROD_ROOT/static" \
      "$PROD_ROOT/main.py" 2>/dev/null || true
    if [[ "$INCLUDE_TESTS" -eq 1 && -L "$PROD_ROOT/tests" ]]; then
      chown -h "${PROD_USER}:${PROD_GROUP}" "$PROD_ROOT/tests" 2>/dev/null || true
    fi
    log "Symlinks enabled. Template/static changes in dev are live immediately."
    log "Python changes still need: ./scripts/deploy_to_production.sh --code"
    show_status
    ;;
  disable)
    disable_symlinks
    chown -R "${PROD_USER}:${PROD_GROUP}" \
      "$PROD_ROOT/app" \
      "$PROD_ROOT/templates" \
      "$PROD_ROOT/static" \
      "$PROD_ROOT/main.py" 2>/dev/null || true
    log "Symlinks disabled — production uses local copies again"
    show_status
    ;;
esac
