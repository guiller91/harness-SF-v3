#!/usr/bin/env bash
# hx — punto de entrada del harness. Uso: ./hx <comando>   (./hx --help)
set -euo pipefail
HX_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HX_ROOT
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "hx: hace falta Python 3.8+ en el PATH" >&2; exit 127; }
exec "$PY" "$HX_ROOT/harness/cli.py" "$@"
