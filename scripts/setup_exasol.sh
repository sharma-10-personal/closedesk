#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

if ! command -v exasol >/dev/null; then
  echo "exasol CLI not found. Install with:"
  echo "  curl https://downloads.exasol.com/exasol-personal/installer.sh | sh"
  exit 1
fi

SECRETS="$HOME/.exasol/personal/deployments/default/secrets.json"
if [[ ! -f "$SECRETS" ]]; then
  echo "No local deployment secrets at $SECRETS"
  echo "Run: exasol install local --auto-approve"
  exit 1
fi

PW="$(python3 -c "import json; print(json.load(open('$SECRETS'))['dbPassword'])")"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exasol connect -k -u sys -p "$PW" -f "$ROOT/sql/00_schema.sql"
echo "CLOSEDESK schema applied."
