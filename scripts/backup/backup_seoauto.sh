#!/usr/bin/env bash
# SEOAuto backup orchestrator
#   (default) / --db       database + env.local
#   --media                uploads/media + data json
#   --source               source code DR
#   --infra                nginx/systemd/cron/rclone
#   --full                 all types
#   --data                 legacy: db + media combined
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

SKIP_UPLOAD=0
MODE_EXPLICIT=0
BACKUP_TRIGGER="${BACKUP_TRIGGER:-scheduled}"
ACTIVE_TYPE=""

backup_parse_args() {
  for arg in "$@"; do
    case "$arg" in
      --dry-run)     DRY_RUN=1 ;;
      --skip-upload) SKIP_UPLOAD=1 ;;
      --db)          BACKUP_MODE_DB=1; MODE_EXPLICIT=1 ;;
      --media)       BACKUP_MODE_MEDIA=1; MODE_EXPLICIT=1 ;;
      --source)      BACKUP_MODE_SOURCE=1; MODE_EXPLICIT=1 ;;
      --infra)       BACKUP_MODE_INFRA=1; MODE_EXPLICIT=1 ;;
      --data)        BACKUP_MODE_DATA=1; MODE_EXPLICIT=1 ;;
      --full)        BACKUP_MODE_DB=1; BACKUP_MODE_MEDIA=1; BACKUP_MODE_SOURCE=1; BACKUP_MODE_INFRA=1; MODE_EXPLICIT=1 ;;
      -h|--help)
        grep '^#   ' "$0" | sed 's/^#   //'
        exit 0
        ;;
      *) echo "Unknown: $arg" >&2; exit 1 ;;
    esac
  done
  if [[ "$MODE_EXPLICIT" -eq 0 ]]; then
    BACKUP_MODE_DB=1
  fi
}

backup_primary_type() {
  if [[ "$BACKUP_MODE_DB" -eq 1 && "$BACKUP_MODE_MEDIA" -eq 0 && "$BACKUP_MODE_SOURCE" -eq 0 && "$BACKUP_MODE_INFRA" -eq 0 ]]; then echo db; return; fi
  if [[ "$BACKUP_MODE_MEDIA" -eq 1 && "$BACKUP_MODE_DB" -eq 0 ]]; then echo media; return; fi
  if [[ "$BACKUP_MODE_SOURCE" -eq 1 && "$BACKUP_MODE_INFRA" -eq 0 && "$BACKUP_MODE_DB" -eq 0 ]]; then echo source; return; fi
  if [[ "$BACKUP_MODE_INFRA" -eq 1 && "$BACKUP_MODE_SOURCE" -eq 0 ]]; then echo infra; return; fi
  echo full
}

backup_write_manifest() {
  local manifest="${RUN_DIR}/manifest.json"
  [[ "$DRY_RUN" -eq 1 ]] && { backup_log "INFO" "[dry-run] Would write manifest.json"; return 0; }
  local types_json=""
  for t in db media source infra data; do
    case "$t" in
      db) [[ "$BACKUP_MODE_DB" -eq 1 ]] && types_json+="\"db\"," ;;
      media) [[ "$BACKUP_MODE_MEDIA" -eq 1 ]] && types_json+="\"media\"," ;;
      source) [[ "$BACKUP_MODE_SOURCE" -eq 1 ]] && types_json+="\"source\"," ;;
      infra) [[ "$BACKUP_MODE_INFRA" -eq 1 ]] && types_json+="\"infra\"," ;;
      data) [[ "$BACKUP_MODE_DATA" -eq 1 ]] && types_json+="\"data\"," ;;
    esac
  done
  types_json="[${types_json%,}]"
  cat > "$manifest" <<EOF
{
  "run_id": "${RUN_ID}",
  "started_at": "$(date -Iseconds)",
  "finished_at": "$(date -Iseconds)",
  "app_root": "${APP_ROOT}",
  "status": "success",
  "backup_types": ${types_json},
  "remote_paths": {
    "db": "$(backup_planned_remote_path_for db)",
    "media": "$(backup_planned_remote_path_for media)",
    "source": "$(backup_planned_remote_path_for source)",
    "infra": "$(backup_planned_remote_path_for infra)"
  },
  "data_backup": {
    "includes": ["postgresql digiseo", "env.local encrypted"],
    "artifacts": ["digiseo.dump.enc", "digiseo.dump.enc.sha256", "env.local.enc", "env.local.enc.sha256"]
  },
  "media_backup": {
    "includes": ["data/users", "data/*.json", "static/uploads", "static/published", "static/reports", "static/downloads"],
    "artifacts": ["media.tar.gz.enc", "media.tar.gz.enc.sha256"]
  },
  "source_backup": {
    "includes": ["app", "templates", "static/js", "static/css", "scripts", "deploy", "main.py", "requirements.txt"],
    "artifacts": ["source.tar.gz.enc", "source.tar.gz.enc.sha256"]
  },
  "infra_backup": {
    "includes": ["nginx", "systemd", "cron", "rclone.conf.enc", "backup.env.example"],
    "artifacts": ["infra.tar.gz.enc", "infra.tar.gz.enc.sha256"]
  },
  "excludes": [".venv", "__pycache__", ".pytest_cache", "node_modules", ".git", "logs", "backups", "*.pyc", "*.log"]
}
EOF
  backup_log "INFO" "Manifest written: manifest.json"
}

backup_run_db() {
  ACTIVE_TYPE=db
  backup_record_start db
  # shellcheck source=backup_pg.sh
  source "$SCRIPT_DIR/backup_pg.sh"
  local dump_file; dump_file="$(backup_pg_dump)"
  [[ "$DRY_RUN" -eq 0 && -f "$dump_file" ]] && backup_encrypt_and_checksum_plain "$dump_file"
  local env_file="${APP_ROOT}/env.local"
  if [[ "$DRY_RUN" -eq 0 && -f "$env_file" ]]; then
    backup_encrypt_file "$env_file" "${RUN_DIR}/env.local.enc"
    backup_checksum_file "${RUN_DIR}/env.local.enc" "${RUN_DIR}/env.local.enc.sha256"
  fi
}

backup_run_media() {
  ACTIVE_TYPE=media
  backup_record_start media
  # shellcheck source=backup_media.sh
  source "$SCRIPT_DIR/backup_media.sh"
  local arc; arc="$(backup_media_archive)"
  [[ "$DRY_RUN" -eq 0 && -f "$arc" ]] && backup_encrypt_and_checksum_plain "$arc"
}

backup_run_source() {
  ACTIVE_TYPE=source
  backup_record_start source
  # shellcheck source=backup_source.sh
  source "$SCRIPT_DIR/backup_source.sh"
  local arc; arc="$(backup_source_archive)"
  [[ "$DRY_RUN" -eq 0 && -f "$arc" ]] && backup_encrypt_and_checksum_plain "$arc"
}

backup_run_infra() {
  ACTIVE_TYPE=infra
  backup_record_start infra
  # shellcheck source=backup_infra.sh
  source "$SCRIPT_DIR/backup_infra.sh"
  local arc; arc="$(backup_infra_archive)"
  [[ "$DRY_RUN" -eq 0 && -f "$arc" ]] && backup_encrypt_and_checksum_plain "$arc"
}

backup_run_data_legacy() {
  BACKUP_MODE_DB=1; BACKUP_MODE_MEDIA=1
  backup_run_db
  backup_run_media
}

backup_main() {
  local start_ts=$(date +%s) status=success err_msg=""
  local remote_db="" remote_media="" remote_source="" remote_infra=""
  trap 'status=failed; err_msg="interrupted"' INT TERM

  backup_parse_args "$@"
  backup_load_env
  backup_check_prereqs
  backup_acquire_lock
  trap backup_release_lock EXIT

  backup_init_run
  backup_check_disk "$BACKUP_LOCAL_DIR"
  ACTIVE_TYPE="$(backup_primary_type)"
  backup_log "INFO" "=== Backup start type=${ACTIVE_TYPE} dry_run=${DRY_RUN} ==="

  if [[ "$BACKUP_MODE_DATA" -eq 1 ]]; then backup_run_data_legacy
  else
    [[ "$BACKUP_MODE_DB" -eq 1 ]] && backup_run_db
    [[ "$BACKUP_MODE_MEDIA" -eq 1 ]] && backup_run_media
    [[ "$BACKUP_MODE_SOURCE" -eq 1 ]] && backup_run_source
    [[ "$BACKUP_MODE_INFRA" -eq 1 ]] && backup_run_infra
  fi

  backup_write_manifest

  if [[ "$SKIP_UPLOAD" -eq 0 ]]; then
    # shellcheck source=backup_upload.sh
    source "$SCRIPT_DIR/backup_upload.sh"
    [[ "$BACKUP_MODE_DB" -eq 1 || "$BACKUP_MODE_DATA" -eq 1 ]] && remote_db="$(backup_upload_db_run "$RUN_DIR")"
    [[ "$BACKUP_MODE_MEDIA" -eq 1 || "$BACKUP_MODE_DATA" -eq 1 ]] && remote_media="$(backup_upload_media_run "$RUN_DIR")"
    [[ "$BACKUP_MODE_SOURCE" -eq 1 ]] && remote_source="$(backup_upload_source_run "$RUN_DIR")"
    [[ "$BACKUP_MODE_INFRA" -eq 1 ]] && remote_infra="$(backup_upload_infra_run "$RUN_DIR")"
  fi

  # shellcheck source=backup_retention.sh
  source "$SCRIPT_DIR/backup_retention.sh"
  for k in db media source infra; do
  case "$k" in
    db) [[ "$BACKUP_MODE_DB" -eq 1 ]] && backup_retention_weekly_monthly_copy db ;;
    media) [[ "$BACKUP_MODE_MEDIA" -eq 1 ]] && backup_retention_weekly_monthly_copy media ;;
    source) [[ "$BACKUP_MODE_SOURCE" -eq 1 ]] && backup_retention_weekly_monthly_copy source ;;
    infra) [[ "$BACKUP_MODE_INFRA" -eq 1 ]] && backup_retention_weekly_monthly_copy infra ;;
  esac
  done
  [[ "$BACKUP_MODE_DB" -eq 1 || "$BACKUP_MODE_MEDIA" -eq 1 || "$BACKUP_MODE_DATA" -eq 1 ]] && backup_retention_run

  if [[ "$SKIP_UPLOAD" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
    if [[ "$BACKUP_MODE_DB" -eq 1 ]]; then
      bash "$SCRIPT_DIR/backup_verify.sh" "$RUN_ID" db || status=failed
    fi
    if [[ "$BACKUP_MODE_MEDIA" -eq 1 ]]; then
      bash "$SCRIPT_DIR/backup_verify.sh" "$RUN_ID" media || status=failed
    fi
    if [[ "$BACKUP_MODE_SOURCE" -eq 1 ]]; then
      bash "$SCRIPT_DIR/backup_verify.sh" "$RUN_ID" source || status=failed
    fi
    if [[ "$BACKUP_MODE_INFRA" -eq 1 ]]; then
      bash "$SCRIPT_DIR/backup_verify.sh" "$RUN_ID" infra || status=failed
    fi
  fi

  local elapsed=$(( $(date +%s) - start_ts ))
  local sz; sz="$(backup_run_dir_size_bytes)"
  for t in db media source infra; do
    local r=""
    case "$t" in db) r="$remote_db";; media) r="$remote_media";; source) r="$remote_source";; infra) r="$remote_infra";; esac
    [[ "$t" == "db" && "$BACKUP_MODE_DB" -eq 0 && "$BACKUP_MODE_DATA" -eq 0 ]] && continue
    [[ "$t" == "media" && "$BACKUP_MODE_MEDIA" -eq 0 && "$BACKUP_MODE_DATA" -eq 0 ]] && continue
    [[ "$t" == "source" && "$BACKUP_MODE_SOURCE" -eq 0 ]] && continue
    [[ "$t" == "infra" && "$BACKUP_MODE_INFRA" -eq 0 ]] && continue
    backup_record_finish "$t" "$status" "$elapsed" "$r" "$sz" "$err_msg"
  done

  backup_log "INFO" "=== Backup finished status=${status} ${elapsed}s size=${sz} ==="
  [[ "$status" == failed ]] && exit 1
}

backup_main "$@"
