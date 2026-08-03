#!/usr/bin/env bash
# Shared helpers for SEOAuto backup scripts.
# shellcheck disable=SC2034
set -euo pipefail

# Prevent re-source from resetting run state
if [[ -n "${BACKUP_LIB_LOADED:-}" ]]; then
  return 0 2>/dev/null || true
fi
BACKUP_LIB_LOADED=1

BACKUP_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_ROOT="${APP_ROOT:-/var/www/seoauto_vn_usr4940/data/www/seoauto.vn}"
BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/var/www/seoauto_vn_usr4940/backups/auto}"
BACKUP_LOG_FILE="${BACKUP_LOG_FILE:-/var/log/seoauto-backup.log}"
BACKUP_LOCK_FILE="${BACKUP_LOCK_FILE:-/var/run/seoauto-backup.lock}"
BACKUP_ENV_FILE="${BACKUP_ENV_FILE:-/etc/seoauto/backup.env}"
BACKUP_KEY_FILE="${BACKUP_KEY_FILE:-/etc/seoauto/backup.key}"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"
RCLONE_DEST="${RCLONE_DEST:-SEOAuto-Backups/prod}"
BACKUP_RETENTION_DAYS_LOCAL="${BACKUP_RETENTION_DAYS_LOCAL:-7}"
BACKUP_RETENTION_DAYS_REMOTE="${BACKUP_RETENTION_DAYS_REMOTE:-90}"
BACKUP_MIN_DISK_MB="${BACKUP_MIN_DISK_MB:-2048}"
DRY_RUN="${DRY_RUN:-0}"

RUN_ID=""
RUN_DIR=""

backup_load_env() {
  if [[ -f "$BACKUP_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$BACKUP_ENV_FILE"
    set +a
  else
    backup_log "WARN" "Config not found: $BACKUP_ENV_FILE — using defaults"
  fi
}

backup_redact_url() {
  local url="${1:-}"
  echo "$url" | sed -E 's#(postgresql(\+[^:/]+)?://)[^:@]+:[^@]+@#\1USER:***@#'
}

backup_log() {
  local level="$1"
  shift
  local msg="$*"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  local line="[$ts] [$level] $msg"
  echo "$line" >&2
  if [[ "$DRY_RUN" -eq 0 && -n "${BACKUP_LOG_FILE:-}" ]]; then
    mkdir -p "$(dirname "$BACKUP_LOG_FILE")" 2>/dev/null || true
    echo "$line" >> "$BACKUP_LOG_FILE" 2>/dev/null || true
  fi
}

backup_init_run() {
  RUN_ID="$(date '+%Y%m%d_%H%M%S')_$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  RUN_DIR="${BACKUP_LOCAL_DIR}/${RUN_ID}"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    mkdir -p "$RUN_DIR"
  fi
  backup_log "INFO" "Run ID: $RUN_ID"
  backup_log "INFO" "App root: $APP_ROOT"
  if [[ -n "${DATABASE_URL:-}" ]]; then
    backup_log "INFO" "Database: $(backup_redact_url "$DATABASE_URL")"
  fi
}

backup_acquire_lock() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would acquire lock: $BACKUP_LOCK_FILE"
    return 0
  fi
  exec 200>"$BACKUP_LOCK_FILE"
  if ! flock -n 200; then
    backup_log "ERROR" "Another backup is running (lock: $BACKUP_LOCK_FILE)"
    exit 1
  fi
  echo "$$" >&200
}

backup_release_lock() {
  if [[ "$DRY_RUN" -eq 0 ]]; then
    flock -u 200 2>/dev/null || true
    rm -f "$BACKUP_LOCK_FILE" 2>/dev/null || true
  fi
}

backup_check_disk() {
  local target_dir="${1:-$BACKUP_LOCAL_DIR}"
  local min_mb="${BACKUP_MIN_DISK_MB:-2048}"
  mkdir -p "$target_dir" 2>/dev/null || true
  local avail_kb
  avail_kb="$(df -Pk "$target_dir" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [[ -z "$avail_kb" ]]; then
    backup_log "WARN" "Cannot determine free disk space for $target_dir"
    return 0
  fi
  local avail_mb=$((avail_kb / 1024))
  backup_log "INFO" "Free disk: ${avail_mb} MB (minimum required: ${min_mb} MB)"
  if [[ "$avail_mb" -lt "$min_mb" ]]; then
    backup_log "ERROR" "Insufficient disk space: ${avail_mb} MB < ${min_mb} MB"
    exit 1
  fi
}

backup_check_prereqs() {
  local missing=()
  for cmd in pg_dump tar sha256sum openssl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      missing+=("$cmd")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    backup_log "ERROR" "Missing commands: ${missing[*]}"
    exit 1
  fi
  if [[ ! -d "$APP_ROOT" ]]; then
    backup_log "ERROR" "APP_ROOT does not exist: $APP_ROOT"
    exit 1
  fi
  if [[ "$DRY_RUN" -eq 0 ]]; then
    if [[ ! -f "$BACKUP_KEY_FILE" ]]; then
      backup_log "ERROR" "Encryption key not found: $BACKUP_KEY_FILE"
      exit 1
    fi
    if [[ ! -r "$BACKUP_KEY_FILE" ]]; then
      backup_log "ERROR" "Cannot read encryption key: $BACKUP_KEY_FILE"
      exit 1
    fi
  fi
}

backup_check_rclone() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would verify rclone remote: ${RCLONE_REMOTE}:"
    return 0
  fi
  if ! command -v rclone >/dev/null 2>&1; then
    backup_log "ERROR" "rclone not installed. Install: apt install rclone"
    backup_log "ERROR" "Then configure: rclone config  (remote name: gdrive)"
    exit 1
  fi
  if ! rclone lsd "${RCLONE_REMOTE}:" >/dev/null 2>&1; then
    backup_log "ERROR" "rclone remote '${RCLONE_REMOTE}' not configured or not accessible"
    backup_log "ERROR" "Run: rclone config"
    backup_log "ERROR" "Then test: rclone lsd ${RCLONE_REMOTE}:"
    exit 1
  fi
  backup_log "INFO" "rclone remote OK: ${RCLONE_REMOTE}:"
}

backup_encrypt_file() {
  local src="$1"
  local dest="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would encrypt: $(basename "$src") -> $(basename "$dest")"
    return 0
  fi
  openssl enc -aes-256-cbc -salt -pbkdf2 -iter 310000 \
    -in "$src" -out "$dest" -pass "file:${BACKUP_KEY_FILE}"
  backup_log "INFO" "Encrypted: $(basename "$dest") ($(backup_human_size "$dest"))"
}

backup_checksum_file() {
  local file="$1"
  local checksum_file="$2"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would checksum: $(basename "$file")"
    return 0
  fi
  sha256sum "$file" > "$checksum_file"
  backup_log "INFO" "Checksum: $(basename "$checksum_file")"
}

backup_human_size() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "0 B"
    return
  fi
  local bytes
  bytes="$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)"
  if [[ "$bytes" -ge 1073741824 ]]; then
    awk "BEGIN {printf \"%.2f GB\", $bytes/1073741824}"
  elif [[ "$bytes" -ge 1048576 ]]; then
    awk "BEGIN {printf \"%.2f MB\", $bytes/1048576}"
  elif [[ "$bytes" -ge 1024 ]]; then
    awk "BEGIN {printf \"%.2f KB\", $bytes/1024}"
  else
    echo "${bytes} B"
  fi
}

backup_pg_url_for_dump() {
  local url="${DATABASE_URL:-}"
  if [[ -z "$url" ]]; then
    backup_log "ERROR" "DATABASE_URL not set in $BACKUP_ENV_FILE"
    exit 1
  fi
  echo "${url/postgresql+psycopg2/postgresql}"
}

backup_remote_date_path() {
  date '+%Y/%m/%d'
}

BACKUP_MODE_DATA=0
BACKUP_MODE_DB=0
BACKUP_MODE_MEDIA=0
BACKUP_MODE_SOURCE=0
BACKUP_MODE_INFRA=0

backup_tar_standard_excludes() {
  backup_tar_excludes=(
    --exclude='.venv'
    --exclude='__pycache__'
    --exclude='.pytest_cache'
    --exclude='node_modules'
    --exclude='.git'
    --exclude='*.log'
    --exclude='*.log.*'
    --exclude='*.pyc'
    --exclude='*.tmp'
    --exclude='*.cache'
    --exclude='backups'
    --exclude='.DS_Store'
  )
}

backup_planned_remote_path_for() {
  local kind="${1:-data}"
  local date_path
  date_path="$(backup_remote_date_path)"
  case "$kind" in
    db)     echo "${RCLONE_REMOTE}:${RCLONE_DEST}/db/${date_path}/${RUN_ID}/" ;;
    media)  echo "${RCLONE_REMOTE}:${RCLONE_DEST}/media/${date_path}/${RUN_ID}/" ;;
    source) echo "${RCLONE_REMOTE}:${RCLONE_DEST}/source/${date_path}/${RUN_ID}/" ;;
    infra)  echo "${RCLONE_REMOTE}:${RCLONE_DEST}/infra/${date_path}/${RUN_ID}/" ;;
    data)   echo "${RCLONE_REMOTE}:${RCLONE_DEST}/${date_path}/${RUN_ID}/" ;;
    *)      echo "${RCLONE_REMOTE}:${RCLONE_DEST}/${date_path}/${RUN_ID}/" ;;
  esac
}

backup_encrypt_and_checksum_plain() {
  local plain="$1"
  if [[ ! -f "$plain" ]]; then
    return 0
  fi
  backup_encrypt_file "$plain" "${plain}.enc"
  backup_checksum_file "${plain}.enc" "${plain}.enc.sha256"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    rm -f "$plain"
  fi
}

backup_standard_excludes_json() {
  cat <<'JSON'
[
  ".venv",
  "__pycache__",
  ".pytest_cache",
  "node_modules",
  ".git",
  "logs",
  "backups",
  "*.pyc",
  "*.log",
  "*.tmp",
  "*.cache"
]
JSON
}



backup_record_start() {
  local btype="$1"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  APP_ROOT="${APP_ROOT}" "$(backup_python_exec)" "${BACKUP_LIB_DIR}/backup_record.py" start     --run-id "${RUN_ID}" --type "${btype}" --trigger "${BACKUP_TRIGGER:-scheduled}"     --local-dir "${RUN_DIR}" 2>/dev/null || backup_log "WARN" "Could not record start in DB"
}

backup_record_finish() {
  local btype="$1" status="$2" duration="$3" remote="$4" size_b="$5" err="${6:-}"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  local checksum="" manifest="${RUN_DIR}/manifest.json"
  local sha_file
  case "$btype" in
    db) sha_file="${RUN_DIR}/digiseo.dump.enc.sha256" ;;
    media) sha_file="${RUN_DIR}/media.tar.gz.enc.sha256" ;;
    source) sha_file="${RUN_DIR}/source.tar.gz.enc.sha256" ;;
    infra) sha_file="${RUN_DIR}/infra.tar.gz.enc.sha256" ;;
  esac
  [[ -f "$sha_file" ]] && checksum="$(awk '{print $1}' "$sha_file")"
  local verify_arg=()
  if [[ "$status" == "success" && "$SKIP_UPLOAD" -eq 0 ]]; then
    verify_arg=(--verify-status verified)
  fi
  APP_ROOT="${APP_ROOT}" "$(backup_python_exec)" "${BACKUP_LIB_DIR}/backup_record.py" finish     --run-id "${RUN_ID}" --status "${status}" --type "${btype}"     --duration "${duration}" --size-bytes "${size_b}" --remote-path "${remote}"     --checksum "${checksum}" --error "${err}" --manifest "${manifest}" "${verify_arg[@]}" 2>/dev/null     || backup_log "WARN" "Could not record finish in DB"
}

backup_run_dir_size_bytes() {
  local d="${1:-$RUN_DIR}"
  du -sb "$d" 2>/dev/null | awk '{print $1}' || echo 0
}


backup_python_exec() {
  if [[ -x "${APP_ROOT}/.venv/bin/python3" ]]; then
    echo "${APP_ROOT}/.venv/bin/python3"
  else
    echo "python3"
  fi
}
