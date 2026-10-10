#!/usr/bin/env bash
# Daily local pg_dump (custom format). Reads DATABASE_URL from shared env.local.
# Does not encrypt; keep 7 daily dumps. Restore: pg_restore -d NEWDB file.dump
set -euo pipefail
ENV_FILE="/var/www/seoauto_vn_usr/data/www/shared/env.local"
OUT_DIR="/var/www/seoauto_vn_usr/data/backups/auto"
LOG="/var/www/seoauto_vn_usr/data/www/seoauto.vn-current/docs/baseline/wave11/pg_dump_cron.log"
mkdir -p "$OUT_DIR"
url=""
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* || "$line" != DATABASE_URL=* ]] && continue
  url="${line#DATABASE_URL=}"
  url="${url%\"}"
  url="${url#\"}"
done < "$ENV_FILE"
url="${url/postgresql+psycopg2:\/\//postgresql:\/\/}"
stamp="$(date +%Y%m%d_%H%M%S)"
out="${OUT_DIR}/digiseo_${stamp}.dump"
pg_dump "$url" --format=custom --no-owner --no-acl -f "$out"
sha256sum "$out" > "${out}.sha256"
find "$OUT_DIR" -name 'digiseo_*.dump' -mtime +7 -delete
find "$OUT_DIR" -name 'digiseo_*.dump.sha256' -mtime +7 -delete
echo "$(date -Iseconds) dump=$(basename "$out") bytes=$(stat -c%s "$out")" >> "$LOG"
