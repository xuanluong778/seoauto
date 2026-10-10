#!/usr/bin/env bash
# Lightweight secret scan for pre-commit / CI. Does not print secret values.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Paths to scan: staged files if in git hook, else all tracked files
if [[ "${1:-}" == "--staged" ]]; then
  mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)
else
  mapfile -t FILES < <(git ls-files 2>/dev/null || true)
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "[secret_scan] nothing to scan"
  exit 0
fi

# Patterns that strongly suggest committed credentials
# shellcheck disable=SC2016
PATTERNS=(
  'sk-[A-Za-z0-9]{20,}'
  'AKIA[0-9A-Z]{16}'
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  'postgres(ql)?://[^[:space:]"]+:[^[:space:]"]+@'
  'redis://:[^[:space:]"]+@'
  'ghp_[A-Za-z0-9]{20,}'
  'xox[baprs]-[A-Za-z0-9-]{10,}'
)

BLOCKED_PATH_REGEX='(^|/)\.env($|\.)|(^|/)env\.local|(^|/)app\.db$|(^|/)data/(api_keys|publishing_sites|content_ai_projects|technical_audits|user_system_settings|google_oauth)\.json$|(^|/)data/serp_snapshots/|\.pem$|\.pgdump$|\.dump$'

FAIL=0
declare -a HITS=()

for f in "${FILES[@]}"; do
  [[ -z "$f" ]] && continue
  [[ -f "$f" ]] || continue
  # skip binaries and this scanner / example env
  case "$f" in
    *.png|*.jpg|*.jpeg|*.gif|*.webp|*.ico|*.woff*|*.ttf|*.pdf|*.zip|*.gz) continue ;;
    .env.example|scripts/secret_scan.sh|.github/workflows/secret-scan.yml) continue ;;
  esac

  if echo "$f" | grep -Eq "$BLOCKED_PATH_REGEX"; then
    HITS+=("blocked_path:$f")
    FAIL=1
    continue
  fi

  # skip large files
  size=$(wc -c <"$f" | tr -d ' ')
  if [[ "$size" -gt 2000000 ]]; then
    continue
  fi

  for pat in "${PATTERNS[@]}"; do
    if grep -nE "$pat" "$f" >/dev/null 2>&1; then
      # report path + pattern name only (no matching text)
      HITS+=("pattern_hit:$f:$pat")
      FAIL=1
      break
    fi
  done
done

if [[ "$FAIL" -ne 0 ]]; then
  echo "[secret_scan] FAIL — potential secrets or blocked paths (values not shown):"
  for h in "${HITS[@]}"; do
    echo "  - $h"
  done
  echo "[secret_scan] Remove secrets, use .env.example placeholders, or allowlist only if false positive."
  exit 1
fi

echo "[secret_scan] OK (${#FILES[@]} file(s))"
exit 0
