#!/usr/bin/env bash
# Utilidades comunes de los gates. Cada gate:
#   - se ejecuta SIEMPRE vía `./hx gate run <nombre>` (que fija las variables HX_* y registra la evidencia)
#   - termina con 0 (verde) o ≠0 (rojo)
#   - deja una línea de resumen con `summary "..."`
set -uo pipefail
# HX_DEBUG=1 ./hx gate run <gate>  ->  traza de cada comando del gate (diagnóstico)
if [ -n "${HX_DEBUG:-}" ]; then set -x; type -a sf >&2 || true; fi

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

# En Windows el instalador oficial deja un `sf` (script sh) que llama a sf.cmd; desde bash eso rompe con rutas con
# espacios ("C:\Program" no se reconoce) y devuelve rc=1 aunque todo vaya bien. Si hay otro `sf` que no pasa por
# sf.cmd (p. ej. el de npm, que lanza node directo), se usa ese. HX_SF fuerza un binario concreto.
_pick_sf() {
  if [ -n "${HX_SF:-}" ]; then printf '%s\n' "$HX_SF"; return; fi
  local first="" c
  while IFS= read -r c; do
    [ "$c" -ef "$HX_ROOT/bin/sf" ] && continue
    [ -n "$first" ] || first="$c"
    if [ -f "$c" ] && ! grep -qs 'sf\.cmd' "$c" 2>/dev/null; then printf '%s\n' "$c"; return; fi
  done < <(type -ap sf 2>/dev/null)
  printf '%s\n' "$first"
}
if command -v sf >/dev/null 2>&1; then
  HX_SF_BIN="$(_pick_sf)"
  if [ -n "$HX_SF_BIN" ] && [ "$HX_SF_BIN" != "$(command -v sf)" ]; then
    sf() { "$HX_SF_BIN" "$@"; }
  fi
fi

# Ficheros de producto cambiados que siguen existiendo (uno por línea).
changed_existing() {
  [ -f "$HX_CHANGED_FILES" ] || return 0
  while IFS= read -r f; do
    f="${f%$'\r'}"
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
    line="${line%$'\r'}"
    [ -n "$line" ] && ITEMS+=("$line")
  done
  return 0
}
