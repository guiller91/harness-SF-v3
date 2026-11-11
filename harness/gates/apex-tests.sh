#!/usr/bin/env bash
# Gate: tests Apex en la org de desarrollo + cobertura POR CLASE de lo que toca la feature.
# Rojo si falla algún test o alguna clase/trigger cambiado queda por debajo de HX_COVERAGE_GATE.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"

outdir="$HX_EVIDENCE_DIR/apex-tests"
rm -rf "$outdir"; mkdir -p "$outdir"

args=(apex run test --target-org "$HX_TARGET_ORG" --code-coverage --result-format json
      --output-dir "$outdir" --wait 60 --json)
if [ "$HX_TEST_LEVEL" = "RunSpecifiedTests" ]; then
  read_items < <(local_test_classes)
  if [ "${#ITEMS[@]}" -eq 0 ]; then
    echo "✗ apexTestLevel=RunSpecifiedTests pero no hay clases de test en los packageDirs."
    summary "no hay clases de test"; exit 1
  fi
  args+=(--test-level RunSpecifiedTests)
  for c in "${ITEMS[@]}"; do args+=(--class-names "$c"); done
  echo "Ejecutando ${#ITEMS[@]} clase(s) de test del proyecto."
else
  args+=(--test-level "$HX_TEST_LEVEL")
fi

echo "\$ sf ${args[*]}"
sf "${args[@]}" > "$outdir/run.json" 2> "$outdir/run.stderr"
rc=$?
[ -s "$outdir/run.stderr" ] && cat "$outdir/run.stderr"

"$HX_PY" "$HX_LIB/coverage.py" --result "$outdir/run.json" --changed "$HX_CHANGED_FILES" \
  --gate "$HX_COVERAGE_GATE" --summary "$HX_SUMMARY_FILE" --cli-exit "$rc"
