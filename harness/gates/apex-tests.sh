#!/usr/bin/env bash
# Gate: tests Apex en la org de desarrollo + cobertura POR CLASE de lo que toca la feature.
# Rojo si falla algun test o alguna clase/trigger cambiado queda por debajo de HX_COVERAGE_GATE.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"

outdir="$HX_EVIDENCE_DIR/apex-tests"
rm -rf "$outdir"; mkdir -p "$outdir"

args=(apex run test --target-org "$HX_TARGET_ORG" --code-coverage --result-format json --wait 60 --json)
if [ "$HX_TEST_LEVEL" = "RunSpecifiedTests" ]; then
  read_items < <("$HX_PY" "$HX_LIB/sfutil.py" changed-apex "$HX_CHANGED_FILES")
  if [ "${#ITEMS[@]}" -eq 0 ]; then
    echo "Sin clases ni triggers Apex cambiados: no hay nada que probar."
    summary "sin cambios Apex"; exit 0
  fi
  # shellcheck disable=SC2086  # HX_PKG_DIRS: varias rutas separadas por espacios
  read_items < <("$HX_PY" "$HX_LIB/sfutil.py" test-classes --changed "$HX_CHANGED_FILES" $HX_PKG_DIRS)
  if [ "${#ITEMS[@]}" -eq 0 ]; then
    echo "[X] Ninguna clase de test cubre los cambios (ni por nombre ni por referencia): escribe sus tests."
    summary "ningún test cubre los cambios Apex"; exit 1
  fi
  args+=(--test-level RunSpecifiedTests)
  for c in "${ITEMS[@]}"; do args+=(--class-names "$c"); done
  echo "Ejecutando ${#ITEMS[@]} clase(s) de test de la feature: ${ITEMS[*]}"
else
  args+=(--test-level "$HX_TEST_LEVEL")
fi

echo "\$ sf ${args[*]}"
sf "${args[@]}" > "$outdir/run.json" 2> "$outdir/run.stderr"
rc=$?
[ -s "$outdir/run.stderr" ] && cat "$outdir/run.stderr"

# Buscar el JSON en diferentes ubicaciones (salida directa o carpeta de salida)
result_file="$outdir/run.json"
if [ ! -s "$result_file" ] && [ -f "$outdir/test-result.json" ]; then
  result_file="$outdir/test-result.json"
fi

"$HX_PY" "$HX_LIB/coverage.py" --result "$result_file" --changed "$HX_CHANGED_FILES" \
  --gate "$HX_COVERAGE_GATE" --summary "$HX_SUMMARY_FILE" --cli-exit "$rc"
