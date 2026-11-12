#!/usr/bin/env bash
# Gate: tests Jest de LWC. Rojo si falla algún test o un componente cambiado no tiene tests.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need node "Instala Node.js LTS"
need npm "Instala Node.js LTS"

if [ ! -f package.json ] || ! grep -q "sfdx-lwc-jest" package.json; then
  echo "[X] package.json no declara @salesforce/sfdx-lwc-jest."
  summary "Jest de LWC sin configurar"; exit 1
fi
if [ ! -d node_modules/@salesforce/sfdx-lwc-jest ]; then
  echo "[X] Dependencias sin instalar. Ejecuta: npm ci   (o npm install)"
  summary "faltan node_modules"; exit 3
fi

missing=0; total=0
while IFS= read -r comp; do
  [ -n "$comp" ] || continue
  total=$((total + 1))
  if ! ls "$comp"/__tests__/*.test.js >/dev/null 2>&1; then
    echo "  [X] sin tests Jest: $comp"
    missing=$((missing + 1))
  fi
done < <(changed_existing | grep -E '/lwc/[^/]+/[^/]+\.(js|html)$' | grep -v '/__tests__/' \
           | sed -E 's#(/lwc/[^/]+)/.*#\1#' | sort -u)

echo "\$ npx sfdx-lwc-jest -- --ci"
npx sfdx-lwc-jest -- --ci
rc=$?

if [ "$missing" -gt 0 ]; then
  summary "$missing de $total componente(s) cambiados sin tests Jest"; exit 1
fi
if [ "$rc" -eq 0 ]; then
  summary "Jest en verde ($total componente(s) cambiados, todos con tests)"
else
  summary "Jest en rojo"
fi
exit "$rc"
