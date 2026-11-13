#!/usr/bin/env bash
# Gate: análisis estático con Salesforce Code Analyzer v5 (Apex, LWC/ESLint, Flows, CPD, RetireJS).
# Rojo si hay alguna violación de severidad <= HX_SEVERITY (1 = crítica ... 5 = info).
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"
# Misma comprobación que `hx doctor`: el plugin figura instalado (`sf code-analyzer --version` no existe).
# (sin tubería: con `set -o pipefail`, `grep -q` cierra antes y `sf` muere por SIGPIPE aunque el plugin exista)
plugins_out=$(sf plugins 2>/dev/null || true)
if ! grep -qi "code-analyzer" <<<"$plugins_out"; then
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
    open(summary, "w").write(f"ENTORNO: code-analyzer terminó con {rc} y sin fichero de resultados")
    sys.exit(3)
viols = data.get("violations") or []
def sev(v):
    try: return int(v.get("severity"))
    except Exception: return 99
env_bad = [v for v in viols if str(v.get("rule", "")).endswith("UninstantiableEngineError")]
bad = [v for v in viols if sev(v) <= thr and v not in env_bad]
msg = f"{len(viols)} violación(es), {len(bad)} de severidad <= {thr}"
if env_bad:
    engines = ", ".join(sorted({str(v.get("rule", "")).split(":")[0] for v in env_bad}))
    msg += f"; ENTORNO: motor(es) no disponible(s): {engines} (no es un fallo del código: configura code-analyzer.yml, ver su cabecera)"
open(summary, "w").write(msg)
for v in env_bad:
    print(f"  [ENTORNO] motor '{str(v.get('rule','')).split(':')[0]}' no se pudo iniciar: arréglalo en code-analyzer.yml (engines.<motor>), no es trabajo del implementer.")
for v in bad[:40]:
    loc = v.get("locations") or [{}]
    loc = loc[v.get("primaryLocationIndex", 0)] if loc else {}
    print(f"  [X] [sev {sev(v)}] {v.get('engine','?')}:{v.get('rule','?')}  "
          f"{loc.get('file','?')}:{loc.get('startLine','?')}  {str(v.get('message',''))[:160]}")
sys.exit(1 if bad else (3 if env_bad else 0))
PY
exit $?
