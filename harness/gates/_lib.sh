#!/usr/bin/env bash
# Utilidades comunes de los gates. Cada gate:
#   - se ejecuta SIEMPRE vía `./hx gate run <nombre>` (que fija las variables HX_* y registra la evidencia)
#   - termina con 0 (verde) o ≠0 (rojo)
#   - deja una línea de resumen con `summary "..."`
set -uo pipefail

: "${HX_ROOT:?Ejecuta los gates con ./hx gate run <nombre>, no directamente}"
cd "$HX_ROOT" || exit 1

HX_PY="${HX_PY:-$(command -v python3 || command -v python)}"

summary() { printf '%s\n' "$*" > "$HX_SUMMARY_FILE"; }

need() { # need <binario> <pista>
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[X] Falta '$1'. $2"
    summary "falta la herramienta $1"
    exit 3
  fi
}

# Ficheros de producto cambiados que siguen existiendo (uno por línea).
changed_existing() {
  [ -f "$HX_CHANGED_FILES" ] || return 0
  while IFS= read -r f; do
    [ -n "$f" ] && [ -f "$f" ] && printf '%s\n' "$f"
  done < "$HX_CHANGED_FILES"
}

# Nombres de las clases de test Apex (con al menos un método de test) de los packageDirs.
local_test_classes() {
  # shellcheck disable=SC2086
  "$HX_PY" "$HX_LIB/sfutil.py" test-classes $HX_PKG_DIRS
}

# Rellena el array global ITEMS con las líneas de stdin (portable: sin mapfile, bash 3.2+).
read_items() {
  ITEMS=()
  local line
  while IFS= read -r line; do
    [ -n "$line" ] && ITEMS+=("$line")
  done
  return 0
}
