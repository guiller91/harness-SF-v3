#!/usr/bin/env bash
# Gate de release (M/L): red de regresión. Ejecuta los tests locales de la org de desarrollo y compara los
# fallos con la línea base guardada. Rojo solo si la feature introduce fallos NUEVOS; los preexistentes se
# avisan pero no bloquean. La primera ejecución crea la línea base.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"

outdir="$HX_EVIDENCE_DIR/regression"
rm -rf "$outdir"; mkdir -p "$outdir"
baseline="$HX_ROOT/.harness/baseline/apex-failures.json"

args=(apex run test --target-org "$HX_TARGET_ORG" --test-level RunLocalTests --result-format json --wait 120 --json)
echo "\$ sf ${args[*]}"
sf "${args[@]}" > "$outdir/run.json" 2> "$outdir/run.stderr"
[ -s "$outdir/run.stderr" ] && cat "$outdir/run.stderr"

"$HX_PY" - "$outdir/run.json" "$baseline" "$HX_SUMMARY_FILE" <<'PY'
import json, os, sys
run, base, summary = sys.argv[1:4]
def done(code, msg):
    open(summary, "w", encoding="utf-8").write(msg + "\n"); sys.exit(code)
try:
    data = json.load(open(run, encoding="utf-8"))
    res = data.get("result") or data
    tests = res["tests"]
except Exception as exc:
    done(3, f"ENTORNO: la ejecución de tests no devolvió JSON utilizable ({exc.__class__.__name__})")
fails = sorted({t.get("FullName") or f"{(t.get('ApexClass') or {}).get('Name','?')}.{t.get('MethodName','?')}"
                for t in tests if (t.get("Outcome") or "").lower() not in ("pass", "passed")})
print(f"Tests locales: {len(tests)} ejecutados . {len(fails)} en rojo")
if not os.path.exists(base):
    os.makedirs(os.path.dirname(base), exist_ok=True)
    json.dump(fails, open(base, "w", encoding="utf-8"), indent=2)
    for f in fails: print(f"  [!] preexistente: {f}")
    done(0, f"línea base creada con {len(fails)} fallo(s) preexistente(s)")
known = set(json.load(open(base, encoding="utf-8")))
new = [f for f in fails if f not in known]
for f in new: print(f"  [X] NUEVO: {f}")
for f in fails:
    if f in known: print(f"  [!] preexistente: {f}")
if new:
    done(1, f"{len(new)} fallo(s) NUEVO(s) respecto a la línea base")
fixed = len(known) - len(set(fails) & known)
json.dump(fails, open(base, "w", encoding="utf-8"), indent=2)   # la línea base solo mejora
done(0, f"sin regresiones ({len(fails)} preexistente(s){', ' + str(fixed) + ' arreglado(s)' if fixed else ''})")
PY
