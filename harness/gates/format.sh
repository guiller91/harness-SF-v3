#!/usr/bin/env bash
# Gate: el código cambiado ya está formateado con prettier, para que un commit (lint-staged) no altere el árbol
# después de generar la evidencia. `./hx advance` (build > verify) ya formatea solo; esto lo confirma.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

read_items < <(changed_existing | grep -E '\.(cls|trigger|js|html|css)$' || true)
if [ "${#ITEMS[@]}" -eq 0 ]; then
  echo ". Sin ficheros que formatear."
  summary "sin ficheros que formatear"; exit 0
fi
"$HX_PY" "$HX_LIB/fmt.py" check "${ITEMS[@]}"
rc=$?
case "$rc" in
  0) summary "${#ITEMS[@]} fichero(s) con formato correcto" ;;
  3) summary "ENTORNO: prettier no disponible (npm install)" ;;
  *) echo "[X] Hay ficheros sin formatear: npx prettier --write <fichero>"
     summary "ficheros sin formatear: npx prettier --write <fichero>"; rc=1 ;;
esac
exit "$rc"
