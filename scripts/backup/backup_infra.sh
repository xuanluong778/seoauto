#!/usr/bin/env bash
# Archive infrastructure config for disaster recovery (no plaintext secrets).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backup_lib.sh
source "$SCRIPT_DIR/backup_lib.sh"

backup_infra_stage() {
  local staging="${RUN_DIR}/.infra_staging"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would stage infra configs"
    echo "$staging"
    return 0
  fi
  rm -rf "$staging"
  mkdir -p "$staging/nginx" "$staging/systemd"

  local nginx_dir="/etc/nginx/fastpanel2-sites/seoauto_vn_usr4940"
  local nginx_files=(
    "seoauto.vn.conf"
    "seoauto.vn.includes"
    "digiseo-upstream.inc"
  )
  for f in "${nginx_files[@]}"; do
    if [[ -f "${nginx_dir}/${f}" ]]; then
      cp -a "${nginx_dir}/${f}" "$staging/nginx/"
      backup_log "INFO" "Staged nginx: $f"
    else
      backup_log "WARN" "nginx file not found: ${nginx_dir}/${f}"
    fi
  done

  mkdir -p "$staging/cron"
  crontab -l -u root > "$staging/cron/root.crontab" 2>/dev/null || true
  backup_log "INFO" "Staged cron: root.crontab"
  shopt -s nullglob
  for sf in /etc/systemd/system/seoauto-backup*.service /etc/systemd/system/seoauto-backup*.timer /etc/systemd/system/digiseo.service; do
    [[ -f "$sf" ]] || continue
    cp -a "$sf" "$staging/systemd/$(basename "$sf")"
    backup_log "INFO" "Staged systemd: $(basename "$sf")"
  done
  shopt -u nullglob
  if [[ -f /root/.config/rclone/rclone.conf ]]; then
    backup_encrypt_file /root/.config/rclone/rclone.conf "$staging/rclone.conf.enc"
    backup_log "INFO" "Staged encrypted: rclone.conf.enc"
  fi

  if [[ -f "${APP_ROOT}/deploy/backup.env.example" ]]; then
    cp -a "${APP_ROOT}/deploy/backup.env.example" "$staging/"
    backup_log "INFO" "Staged deploy/backup.env.example"
  fi

  echo "$staging"
}

backup_infra_archive() {
  local out_file="${RUN_DIR}/infra.tar.gz"
  local staging
  staging="$(backup_infra_stage)"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    backup_log "INFO" "[dry-run] Would create infra.tar.gz"
    echo "$out_file"
    return 0
  fi

  backup_log "INFO" "Creating infra archive..."
  tar czf "$out_file" -C "$staging" .
  rm -rf "$staging"

  local file_count
  file_count="$(tar tzf "$out_file" 2>/dev/null | wc -l | tr -d ' ')"
  backup_log "INFO" "Infra archive: infra.tar.gz ($(backup_human_size "$out_file"), ${file_count} entries)"
  echo "$out_file"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  backup_load_env
  RUN_DIR="${1:?RUN_DIR required}"
  backup_infra_archive
fi
