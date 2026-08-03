#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

backup_files_archive() {
  local out_file="${RUN_DIR}/files.tar.gz"
  local staging="${RUN_DIR}/.staging"
  local env_encrypted="${RUN_DIR}/env.local.enc"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would archive data/users, data/*.json, static/{uploads,published,reports,downloads}"
    backup_log "INFO" "[dry-run] Would encrypt env.local separately"
    echo "$out_file"
    return 0
  fi

  mkdir -p "$staging"
  local paths_to_copy=(
    "data/users"
    "static/uploads"
    "static/published"
    "static/reports"
    "static/downloads"
  )

  for rel in "${paths_to_copy[@]}"; do
    local src="${APP_ROOT}/${rel}"
    if [[ -e "$src" ]]; then
      local dest_dir
      dest_dir="$(dirname "${staging}/${rel}")"
      mkdir -p "$dest_dir"
      backup_log "INFO" "Staging: $rel"
      if command -v rsync >/dev/null 2>&1; then
        rsync -a \
          --exclude='.venv/' \
          --exclude='__pycache__/' \
          --exclude='.pytest_cache/' \
          --exclude='node_modules/' \
          --exclude='*.log' \
          --exclude='*.log.*' \
          --exclude='*.tmp' \
          --exclude='*.cache' \
          --exclude='.DS_Store' \
          "$src" "$dest_dir/"
      else
        cp -a "$src" "$dest_dir/"
      fi
    else
      backup_log "WARN" "Path not found (skipped): $rel"
    fi
  done

  if [[ -d "${APP_ROOT}/data" ]]; then
    mkdir -p "${staging}/data"
    shopt -s nullglob
    local json_files=("${APP_ROOT}"/data/*.json)
    shopt -u nullglob
    if [[ ${#json_files[@]} -gt 0 ]]; then
      backup_log "INFO" "Staging: data/*.json (${#json_files[@]} files)"
      cp -a "${json_files[@]}" "${staging}/data/"
    fi
  fi

  backup_log "INFO" "Creating tar archive..."
  tar czf "$out_file" \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='node_modules' \
    --exclude='*.log' \
    --exclude='*.log.*' \
    --exclude='*.tmp' \
    --exclude='*.cache' \
    -C "$staging" .

  rm -rf "$staging"
  backup_log "INFO" "Files archive: $(basename "$out_file") ($(backup_human_size "$out_file"))"

  local env_file="${APP_ROOT}/env.local"
  if [[ -f "$env_file" ]]; then
    backup_log "INFO" "Encrypting env.local..."
    backup_encrypt_file "$env_file" "$env_encrypted"
  else
    backup_log "WARN" "env.local not found — skipping config backup"
  fi

  echo "$out_file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  RUN_DIR="${1:?RUN_DIR required}"
  backup_files_archive
fi
