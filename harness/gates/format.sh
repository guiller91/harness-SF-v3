#!/usr/bin/env bash
# Gate: el código cambiado ya está formateado con prettier, para que un commit (lint-staged) no altere el árbol
# después de generar la evidencia (el hash cambiaría y caducarían gates y revisiones).
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need npx "Instala Node.js LTS"

read_items < <(changed_existing | grep -E '\.(cls|trigger|js|html|css)$' || true)
if [ "${#ITEMS[@]}" -eq 0 ]; then
  echo ". Sin ficheros que formatear."
  summary "sin ficheros que formatear"; exit 0
fi
if [ ! -d node_modules/prettier ]; then
  echo "[X] prettier no está instalado en el proyecto (npm install)."
  summary "prettier sin instalar: npm install"; exit 1
fi
if npx --no-install prettier --check "${ITEMS[@]}"; then
  summary "${#ITEMS[@]} fichero(s) con formato correcto"
else
  echo "[X] Hay ficheros sin formatear. Arréglalo con: npx prettier --write <fichero>"
  summary "ficheros sin formatear: npx prettier --write <fichero>"; exit 1
fi
