#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

backup_upload_artifacts() {
  local run_dir="${1:-}"
  local remote_kind="${2:-data}"
  shift 2
  local artifacts=("$@")

  if [[ -z "$run_dir" ]]; then
    run_dir="${BACKUP_LOCAL_DIR}/${RUN_ID}"
  fi
  local remote_base
  remote_base="$(backup_planned_remote_path_for "$remote_kind")"
  local uploaded=0

  backup_check_rclone

  for name in "${artifacts[@]}"; do
    local local_file="${run_dir}/${name}"
    if [[ ! -f "$local_file" ]]; then
      if [[ "$name" == env.local.enc* ]]; then
        continue
      fi
      backup_log "WARN" "Artifact missing (skipped): $name"
      continue
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
      backup_log "INFO" "[dry-run] Would upload: $name -> ${remote_base}"
    else
      backup_log "INFO" "Uploading: $name -> ${remote_base}"
      rclone copyto "$local_file" "${remote_base}${name}" \
        --timeout 30m \
        --retries 3 \
        --low-level-retries 10
      uploaded=$((uploaded + 1))
    fi
  done

  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Remote path: ${remote_base}"
  else
    backup_log "INFO" "Upload complete: ${uploaded} files -> ${remote_base}"
  fi
  echo "${remote_base}"
}

backup_upload_run() {
  local run_dir="${1:-}"
  if [[ -z "$run_dir" ]]; then
    run_dir="${BACKUP_LOCAL_DIR}/${RUN_ID}"
  fi
  backup_upload_artifacts "$run_dir" "data" \
    "digiseo.dump.enc" \
    "digiseo.dump.enc.sha256" \
    "files.tar.gz.enc" \
    "files.tar.gz.enc.sha256" \
    "env.local.enc" \
    "env.local.enc.sha256" \
    "manifest.json"
}

backup_upload_source_run() {
  local run_dir="${1:-}"
  backup_upload_artifacts "$run_dir" "source" \
    "source.tar.gz.enc" \
    "source.tar.gz.enc.sha256" \
    "manifest.json"
}

backup_upload_infra_run() {
  local run_dir="${1:-}"
  backup_upload_artifacts "$run_dir" "infra" \
    "infra.tar.gz.enc" \
    "infra.tar.gz.enc.sha256" \
    "manifest.json"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  RUN_DIR="${1:?RUN_DIR required}"
  backup_upload_run "$RUN_DIR"
fi

backup_upload_db_run() {
  local run_dir="${1:-}"
  backup_upload_artifacts "$run_dir" "db" \
    "digiseo.dump.enc" "digiseo.dump.enc.sha256" \
    "env.local.enc" "env.local.enc.sha256" "manifest.json"
}

backup_upload_media_run() {
  local run_dir="${1:-}"
  backup_upload_artifacts "$run_dir" "media" \
    "media.tar.gz.enc" "media.tar.gz.enc.sha256" "manifest.json"
}
