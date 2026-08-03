#!/usr/bin/env bash
# Archive application source code for disaster recovery.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

backup_source_paths() {
  local paths=()
  local candidates=(
    "app"
    "templates"
    "static/js"
    "static/css"
    "main.py"
    "requirements.txt"
    "scripts"
    "deploy"
  )
  for rel in "${candidates[@]}"; do
    if [[ -e "${APP_ROOT}/${rel}" ]]; then
      paths+=("$rel")
    else
      backup_log "WARN" "Source path not found (skipped): $rel"
    fi
  done
  if [[ -d "${APP_ROOT}/static/chatbot" ]]; then
    paths+=("static/chatbot")
  fi
  if [[ -d "${APP_ROOT}/migrations" ]]; then
    paths+=("migrations")
  elif [[ -d "${APP_ROOT}/app/migrations" ]]; then
    paths+=("app/migrations")
  fi
  if [[ -f "${APP_ROOT}/alembic.ini" ]]; then
    paths+=("alembic.ini")
  fi
  printf '%s\n' "${paths[@]}"
}

backup_source_archive() {
  local out_file="${RUN_DIR}/source.tar.gz"
  backup_tar_standard_excludes
  mapfile -t src_paths < <(backup_source_paths)

  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would archive source (${#src_paths[@]} paths) -> source.tar.gz"
    echo "$out_file"
    return 0
  fi

  if [[ ${#src_paths[@]} -eq 0 ]]; then
    backup_log "ERROR" "No source paths to archive"
    exit 1
  fi

  backup_log "INFO" "Archiving source (${#src_paths[@]} paths)..."
  tar czf "$out_file" \
    "${backup_tar_excludes[@]}" \
    -C "$APP_ROOT" \
    "${src_paths[@]}"

  local file_count
  file_count="$(tar tzf "$out_file" 2>/dev/null | wc -l | tr -d ' ')"
  backup_log "INFO" "Source archive: source.tar.gz ($(backup_human_size "$out_file"), ${file_count} entries)"
  echo "$out_file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  RUN_DIR="${1:?RUN_DIR required}"
  backup_source_archive
fi
