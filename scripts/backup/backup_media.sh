#!/usr/bin/env bash
# Archive uploads/media and data JSON stores.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

backup_media_archive() {
  local out_file="${RUN_DIR}/media.tar.gz"
  local staging="${RUN_DIR}/.media_staging"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would archive uploads/media"
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
  backup_tar_standard_excludes
  for rel in "${paths_to_copy[@]}"; do
    local src="${APP_ROOT}/${rel}"
    if [[ -e "$src" ]]; then
      local dest_dir
      dest_dir="$(dirname "${staging}/${rel}")"
      mkdir -p "$dest_dir"
      backup_log "INFO" "Staging: $rel"
      rsync -a "${backup_tar_excludes[@]/#/--exclude=}" "$src" "$dest_dir/" 2>/dev/null || \
        rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.log' "$src" "$dest_dir/"
    fi
  done
  if [[ -d "${APP_ROOT}/data" ]]; then
    mkdir -p "${staging}/data"
    shopt -s nullglob
    local json_files=("${APP_ROOT}"/data/*.json)
    shopt -u nullglob
    [[ ${#json_files[@]} -gt 0 ]] && cp -a "${json_files[@]}" "${staging}/data/"
  fi
  tar czf "$out_file" "${backup_tar_excludes[@]}" -C "$staging" .
  rm -rf "$staging"
  local fc
  fc="$(tar tzf "$out_file" | wc -l | tr -d ' ')"
  backup_log "INFO" "Media archive: media.tar.gz ($(backup_human_size "$out_file"), ${fc} entries)"
  echo "$out_file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  RUN_DIR="${1:?RUN_DIR required}"
  backup_media_archive
fi
