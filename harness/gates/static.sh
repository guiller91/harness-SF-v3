#!/usr/bin/env bash
# Gate: análisis estático con Salesforce Code Analyzer v5 (Apex, LWC/ESLint, Flows, CPD, RetireJS).
# Rojo si hay alguna violación de severidad <= HX_SEVERITY (1 = crítica ... 5 = info).
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"
# Verifica ejecutando directamente el comando del plugin
if ! sf code-analyzer --version >/dev/null 2>&1; then
  echo "[X] Code Analyzer no accesible: sf plugins install code-analyzer"
  summary "falta el plugin code-analyzer"; exit 3
fi
echo ". Verificando Code Analyzer..."

args=(code-analyzer run --view table --severity-threshold "$HX_SEVERITY")
for d in $HX_PKG_DIRS; do [ -d "$d" ] && args+=(--workspace "$d"); done
for sel in $HX_RULE_SELECTORS; do args+=(--rule-selector "$sel"); done
[ -n "${HX_ANALYZER_CONFIG:-}" ] && [ -f "$HX_ANALYZER_CONFIG" ] && args+=(--config-file "$HX_ANALYZER_CONFIG")

if [ "${HX_ANALYZER_SCOPE:-changed}" = "changed" ]; then
  read_items < <(changed_existing)
  if [ "${#ITEMS[@]}" -eq 0 ]; then
    echo ". No hay ficheros de producto cambiados que analizar."
    summary "sin ficheros que analizar"; exit 0
  fi
  for t in "${ITEMS[@]}"; do args+=(--target "$t"); done
  echo "Analizando ${#ITEMS[@]} fichero(s) cambiado(s) (analyzer.scope=changed)."
else
  echo "Analizando todo el workspace (analyzer.scope=all)."
fi

results="$HX_EVIDENCE_DIR/static-results.json"
rm -f "$results"
args+=(--output-file "$results")

echo "\$ sf ${args[*]}"
sf "${args[@]}"
rc=$?

"$HX_PY" - "$results" "$HX_SEVERITY" "$rc" "$HX_SUMMARY_FILE" <<'PY'
import json, sys
path, thr, rc, summary = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    open(summary, "w").write(f"code-analyzer terminó con {rc} y sin fichero de resultados")
    sys.exit(0)
viols = data.get("violations") or []
def sev(v):
    try: return int(v.get("severity"))
    except Exception: return 99
bad = [v for v in viols if sev(v) <= thr]
open(summary, "w").write(f"{len(viols)} violación(es), {len(bad)} de severidad <= {thr}")
for v in bad[:40]:
    loc = v.get("locations") or [{}]
    loc = loc[v.get("primaryLocationIndex", 0)] if loc else {}
    print(f"  [X] [sev {sev(v)}] {v.get('engine','?')}:{v.get('rule','?')}  "
          f"{loc.get('file','?')}:{loc.get('startLine','?')}  {str(v.get('message',''))[:160]}")
PY
exit "$rc"
