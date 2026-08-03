#!/usr/bin/env bash
# Verify backup artifacts locally and on Google Drive.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

RUN_ID="${1:?run_id required}"
KIND="${2:-db}"
BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/var/www/seoauto_vn_usr4940/backups/auto}"
RUN_DIR="${BACKUP_LOCAL_DIR}/${RUN_ID}"

backup_load_env

if [[ ! -d "$RUN_DIR" ]]; then
  backup_log "ERROR" "Run dir not found: $RUN_DIR"
  exit 1
fi

declare -a artifacts=()
case "$KIND" in
  db)    artifacts=("digiseo.dump.enc" "digiseo.dump.enc.sha256" "env.local.enc" "manifest.json") ;;
  media) artifacts=("media.tar.gz.enc" "media.tar.gz.enc.sha256" "manifest.json") ;;
  source) artifacts=("source.tar.gz.enc" "source.tar.gz.enc.sha256" "manifest.json") ;;
  infra) artifacts=("infra.tar.gz.enc" "infra.tar.gz.enc.sha256" "manifest.json") ;;
  *) backup_log "ERROR" "Unknown kind: $KIND"; exit 1 ;;
esac

backup_log "INFO" "Verify local checksums for $RUN_ID ($KIND)"
for name in "${artifacts[@]}"; do
  [[ "$name" == *.sha256 ]] && continue
  local_sha="${RUN_DIR}/${name}.sha256"
  if [[ -f "$local_sha" ]]; then
    (cd "$RUN_DIR" && sha256sum -c "$(basename "$local_sha")") || exit 1
  fi
done

backup_check_rclone
remote_base="$(backup_planned_remote_path_for "$KIND")"
backup_log "INFO" "Verify remote: ${remote_base}"
for name in "${artifacts[@]}"; do
  if ! rclone lsf "${remote_base}${name}" >/dev/null 2>&1; then
    backup_log "ERROR" "Missing on Drive: ${name}"
    exit 1
  fi
  backup_log "INFO" "Remote OK: ${name}"
done

backup_log "INFO" "Verify PASS: $RUN_ID"
APP_ROOT="${APP_ROOT}" python3 "$SCRIPT_DIR/backup_record.py" finish \
  --run-id "$RUN_ID" --status success --verify-status verified 2>/dev/null || true
exit 0
