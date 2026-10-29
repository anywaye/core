#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f mise.toml ] && command -v mise >/dev/null 2>&1 \
  && mise tasks ls 2>/dev/null | grep -qE '^prime([[:space:]]|$)'; then
  exec mise run prime
fi

exec bin/prime
