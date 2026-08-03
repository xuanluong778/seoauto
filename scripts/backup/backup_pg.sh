#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

backup_pg_dump() {
  local out_file="${RUN_DIR}/digiseo.dump"
  local pg_url
  pg_url="$(backup_pg_url_for_dump)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would pg_dump -Fc -> $out_file"
  else
    backup_log "INFO" "Starting pg_dump (custom format)..."
    pg_dump "$pg_url" --format=custom --no-owner --no-acl -f "$out_file"
    backup_log "INFO" "pg_dump complete: $(basename "$out_file") ($(backup_human_size "$out_file"))"
  fi
  echo "$out_file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  RUN_DIR="${1:?RUN_DIR required}"
  backup_pg_dump
fi
