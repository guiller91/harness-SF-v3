#!/usr/bin/env bash
# install.sh — instala el harness en un proyecto Salesforce DX existente.
#   ./install.sh /ruta/a/mi-proyecto-sfdx
# Copia el motor, los agentes, las skills y los hooks. No toca force-app/, sfdx-project.json,
# package.json ni nada que ya exista (salvo que pases --force para actualizar el harness).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORCE=0
DEST=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) DEST="$arg" ;;
  esac
done
[ -n "$DEST" ] || { echo "uso: ./install.sh <proyecto-sfdx> [--force]" >&2; exit 2; }
[ -d "$DEST" ] || { echo "No existe el directorio: $DEST" >&2; exit 2; }
DEST="$(cd "$DEST" && pwd)"
[ -f "$DEST/sfdx-project.json" ] || { echo "$DEST no parece un proyecto SFDX (falta sfdx-project.json)." >&2; exit 2; }
[ "$DEST" != "$SRC" ] || { echo "El destino es el propio harness." >&2; exit 2; }

if [ -d "$DEST/harness" ] && [ "$FORCE" -ne 1 ]; then
  echo "Ya hay un harness en $DEST. Usa --force para actualizar el motor (no toca tu estado ni tu config)." >&2
  exit 1
fi

copy_tree() { # sobrescribe: es el motor del harness
  local rel="$1"
  mkdir -p "$DEST/$rel"
  (cd "$SRC/$rel" && find . -type f ! -path '*/__pycache__/*' -print0) | while IFS= read -r -d '' f; do
    mkdir -p "$DEST/$rel/$(dirname "$f")"
    cp "$SRC/$rel/$f" "$DEST/$rel/$f"
  done
  echo "  ✓ $rel/"
}
copy_new() { # solo si no existe: es tuyo
  local rel="$1"
  if [ -e "$DEST/$rel" ]; then echo "  · $rel (ya existe, no se toca)"; else
    mkdir -p "$(dirname "$DEST/$rel")"; cp "$SRC/$rel" "$DEST/$rel"; echo "  ✓ $rel"; fi
}

echo "Instalando el harness en $DEST"
for d in harness .claude/skills .claude/hooks benchmarks bin; do copy_tree "$d"; done
if [ ! -f "$DEST/.claude/settings.json" ]; then mkdir -p "$DEST/.claude"; cp "$SRC/.claude/settings.json" "$DEST/.claude/settings.json"; echo "  ✓ .claude/settings.json"; fi
# Migración: los hooks ya no llaman a `python3` directo (en Windows es el stub de la Store y los
# guardas no se ejecutaban). Ahora pasan por .claude/hooks/run, que busca un Python que funcione.
# shellcheck disable=SC2016  # los $ son literales del JSON, no deben expandirse
if [ -f "$DEST/.claude/settings.json" ] && grep -qF 'python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/' "$DEST/.claude/settings.json"; then
  sed -i.bak 's#python3 \\"\$CLAUDE_PROJECT_DIR/\.claude/hooks/\([A-Za-z0-9_.-]*\)\\"#sh \\"$CLAUDE_PROJECT_DIR/.claude/hooks/run\\" \1#' "$DEST/.claude/settings.json"
  rm -f "$DEST/.claude/settings.json.bak"
  echo "  ✓ .claude/settings.json (hooks migrados al lanzador .claude/hooks/run)"
fi

# Agentes, hooks nuevos en settings.json y .gitignore: sin pisar lo personalizado (harness/lib/upgrade.py).
HX_SRC="$SRC" HX_DEST="$DEST" sh "$DEST/.claude/hooks/run" ../../harness/lib/upgrade.py \
  || { echo "  ✗ no se pudo completar la actualización de agentes/hooks (¿Python 3.8+?)" >&2; exit 1; }
cp "$SRC/hx" "$DEST/hx"; chmod +x "$DEST/hx" "$DEST"/harness/gates/*.sh "$DEST/bin/sf"; echo "  ✓ hx"
for f in CLAUDE.md AGENTS.md CHECKPOINTS.md docs/workflow.md docs/security-model.md; do
  if [ "$FORCE" -eq 1 ] || [ ! -e "$DEST/$f" ]; then mkdir -p "$(dirname "$DEST/$f")"; cp "$SRC/$f" "$DEST/$f"; echo "  ✓ $f"
  else echo "  · $f (ya existe: revisa y fusiona a mano con el del harness)"; fi
done
for f in harness.config.json feature_list.json code-analyzer.yml docs/architecture.md \
         docs/conventions.md progress/current.md progress/history.md CHANGELOG.md jest.config.js .prettierrc \
         .github/workflows/salesforce-validate.yml; do copy_new "$f"; done
mkdir -p "$DEST/docs/specs" "$DEST/docs/adr" "$DEST/manifest"

# Finales de línea: los scripts deben ser LF aunque Git (Windows) convierta a CRLF.
if ! grep -q "hooks/run text eol=lf" "$DEST/.gitattributes" 2>/dev/null; then
  if [ -s "$DEST/.gitattributes" ]; then echo >> "$DEST/.gitattributes"; fi
  cat "$SRC/.gitattributes" >> "$DEST/.gitattributes"
  echo "  ✓ .gitattributes (scripts del harness siempre en LF)"
fi

if ! grep -qx "\.claude/settings\.local\.json" "$DEST/.gitignore" 2>/dev/null; then
  echo ".claude/settings.local.json" >> "$DEST/.gitignore"
fi

cat <<MSG

Hecho. Siguientes pasos en $DEST:
  1. Edita harness.config.json: project, org.model (scratch|sandbox), org.targetOrgAlias y packageDirs.
  2. Si usas Jest: añade "@salesforce/sfdx-lwc-jest" a tu package.json y un script "test:unit".
  3. Adapta docs/conventions.md a tu equipo.
  4. ./hx doctor          (entorno, org y coherencia)
  5. git add -A && git commit -m "Instala harness-SF"
  6. Abre Claude Code en el proyecto y describe tu primera feature.
MSG
