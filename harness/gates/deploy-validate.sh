#!/usr/bin/env bash
# Gate de entrega: validación check-only (no guarda nada en la org) del artefacto de release,
# con tests. Usa manifest/<feature>/package.xml si existe; si no, los packageDirs completos.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
need sf "npm install -g @salesforce/cli"

args=(project deploy validate --target-org "$HX_VALIDATION_ORG" --wait 60)
if [ -f "$HX_MANIFEST" ]; then
  args+=(--manifest "$HX_MANIFEST")
  dest="$(dirname "$HX_MANIFEST")/destructiveChanges.xml"
  [ -f "$dest" ] && args+=(--post-destructive-changes "$dest")
  echo "Validando el manifest de la feature: ${HX_MANIFEST#"$HX_ROOT"/}"
else
  for d in $HX_PKG_DIRS; do [ -d "$d" ] && args+=(--source-dir "$d"); done
  echo "Sin manifest de feature; validando los packageDirs completos."
fi

if [ "$HX_TEST_LEVEL" = "RunSpecifiedTests" ]; then
  # Solo los tests que cubren lo que cambia la feature (mismo criterio que el gate apex-tests).
  # shellcheck disable=SC2086  # HX_PKG_DIRS: varias rutas separadas por espacios
  read_items < <("$HX_PY" "$HX_LIB/sfutil.py" test-classes --changed "$HX_CHANGED_FILES" $HX_PKG_DIRS)
  changed_apex=$("$HX_PY" "$HX_LIB/sfutil.py" changed-apex "$HX_CHANGED_FILES")
  if [ -z "$changed_apex" ]; then
    args+=(--test-level NoTestRun)   # sin Apex en el cambio: se valida la metadata sin tests
  elif [ "${#ITEMS[@]}" -eq 0 ]; then
    echo "[X] Ninguna clase de test cubre los cambios Apex: escribe sus tests."
    summary "ningún test cubre los cambios Apex"; exit 1
  else
    args+=(--test-level RunSpecifiedTests)
    for c in "${ITEMS[@]}"; do args+=(--tests "$c"); done
  fi
else
  args+=(--test-level "$HX_TEST_LEVEL")
fi

echo "\$ sf ${args[*]}"
sf "${args[@]}"
rc=$?
if [ "$rc" -eq 0 ]; then
  summary "deploy validate Succeeded contra '$HX_VALIDATION_ORG'"
else
  summary "deploy validate FALLÓ contra '$HX_VALIDATION_ORG'"
fi
exit "$rc"
