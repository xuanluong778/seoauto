#!/usr/bin/env bash
# Deploy templates/static only — delegates to deploy_to_production.sh (no backend restart).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/deploy_to_production.sh" --static "$@"
