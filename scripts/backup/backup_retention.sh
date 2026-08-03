#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

BACKUP_RETENTION_WEEKLY_WEEKS="${BACKUP_RETENTION_WEEKLY_WEEKS:-8}"
BACKUP_RETENTION_MONTHLY_MONTHS="${BACKUP_RETENTION_MONTHLY_MONTHS:-12}"

backup_retention_local() {
  local days="${BACKUP_RETENTION_DAYS_LOCAL:-30}"
  backup_log "INFO" "Local retention: >${days} days in ${BACKUP_LOCAL_DIR}"
  if [[ "$DRY_RUN" -eq 1 ]]; then return 0; fi
  local count=0
  while IFS= read -r old_dir; do
    [[ -z "$old_dir" ]] && continue
    rm -rf "$old_dir"
    count=$((count + 1))
  done < <(find "$BACKUP_LOCAL_DIR" -mindepth 1 -maxdepth 1 -type d -mtime "+${days}" 2>/dev/null)
  backup_log "INFO" "Local retention: removed ${count} run(s)"
}

backup_retention_tiered_remote() {
  if ! command -v rclone >/dev/null 2>&1; then
    backup_log "WARN" "rclone missing — skip remote retention"
    return 0
  fi
  local days="${BACKUP_RETENTION_DAYS_REMOTE:-30}"
  local weekly_days=$((BACKUP_RETENTION_WEEKLY_WEEKS * 7))
  local monthly_days=$((BACKUP_RETENTION_MONTHLY_MONTHS * 30))
  for kind in db media source infra data; do
    local base="${RCLONE_REMOTE}:${RCLONE_DEST}"
  local path="${base}/${kind}/"
    if [[ "$kind" == "data" ]]; then path="${base}/"; fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
      backup_log "INFO" "[dry-run] Would delete daily ${path} older than ${days}d"
      continue
    fi
    rclone delete "$path" --min-age "${days}d" --rmdirs --timeout 30m 2>/dev/null \
      || backup_log "WARN" "Retention warnings: ${path}"
  done
  if [[ "$DRY_RUN" -eq 0 ]]; then
    rclone delete "${RCLONE_REMOTE}:${RCLONE_DEST}/weekly/" --min-age "${weekly_days}d" --rmdirs --timeout 30m 2>/dev/null || true
    rclone delete "${RCLONE_REMOTE}:${RCLONE_DEST}/monthly/" --min-age "${monthly_days}d" --rmdirs --timeout 30m 2>/dev/null || true
  fi
  backup_log "INFO" "Remote retention done (daily ${days}d, weekly ${weekly_days}d, monthly ${monthly_days}d)"
}

backup_retention_weekly_monthly_copy() {
  local kind="${1:-db}"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  command -v rclone >/dev/null 2>&1 || return 0
  local src
  src="$(backup_planned_remote_path_for "$kind")"
  local dow dom week month
  dow="$(date +%u)"
  dom="$(date +%d)"
  week="$(date +%G-W%V)"
  month="$(date +%Y-%m)"
  if [[ "$dow" -eq 7 ]]; then
    backup_log "INFO" "Weekly copy: ${kind} -> weekly/${week}/"
    rclone copy "$src" "${RCLONE_REMOTE}:${RCLONE_DEST}/weekly/${kind}/${week}/${RUN_ID}/" --timeout 30m 2>/dev/null || true
  fi
  if [[ "$dom" == "01" ]]; then
    backup_log "INFO" "Monthly copy: ${kind} -> monthly/${month}/"
    rclone copy "$src" "${RCLONE_REMOTE}:${RCLONE_DEST}/monthly/${kind}/${month}/${RUN_ID}/" --timeout 30m 2>/dev/null || true
  fi
}

backup_retention_run() {
  backup_retention_local
  backup_retention_tiered_remote
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  backup_retention_run
fi
