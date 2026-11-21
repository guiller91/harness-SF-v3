"""Paso de actualización de install.sh (lo lanza con .claude/hooks/run, que sabe encontrar Python).

Variables: HX_SRC (el harness) y HX_DEST (tu proyecto). Hace tres cosas sin pisar lo que es tuyo:

1. Agentes (.claude/agents/*.md): si no has tocado uno, se actualiza. Si lo personalizaste (por ejemplo
   desde el centro de control), se conserva el tuyo y la versión nueva queda al lado como
   `<rol>.md.upstream` para que compares. Se recuerda qué se instaló en `.claude/agents/.installed.json`.
2. Hooks (.claude/settings.json): añade los grupos de hooks nuevos del harness que tu settings.json no
   tenga todavía. No quita ni cambia nada tuyo.
3. .gitignore: añade las entradas del harness que falten.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

SRC = Path(os.environ["HX_SRC"])
DEST = Path(os.environ["HX_DEST"])


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def customized_by_panel(name: str) -> bool:
    events = DEST / ".harness" / "events.jsonl"
    if not events.exists():
        return False
    needle = f'".claude/agents/{name}.md"'
    return any('"config_change"' in ln and needle in ln
               for ln in events.read_text(encoding="utf-8", errors="replace").splitlines())


def agents() -> None:
    src_dir, dst_dir = SRC / ".claude" / "agents", DEST / ".claude" / "agents"
    dst_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dst_dir / ".installed.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    kept, updated, new = [], 0, 0
    record = {}
    for src in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src.name
        upstream = dst_dir / f"{src.name}.upstream"
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
            new += 1
            record[src.name] = sha(src)
            continue
        current = sha(dst)
        if current == sha(src):
            upstream.unlink(missing_ok=True)
            record[src.name] = current
            continue
        installed = (manifest or {}).get(src.name)
        mine = current != installed if manifest is not None else customized_by_panel(src.stem)
        if mine:
            upstream.write_bytes(src.read_bytes())
            kept.append(src.name)
            record[src.name] = installed or ""
        else:
            dst.write_bytes(src.read_bytes())
            upstream.unlink(missing_ok=True)
            updated += 1
            record[src.name] = sha(src)
    manifest_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  ✓ .claude/agents/ ({updated} actualizados, {new} nuevos)")
    for name in kept:
        print(f"  · .claude/agents/{name}: lo personalizaste; se conserva. La versión nueva está en {name}.upstream")


HOOK_SCRIPT = re.compile(r"hooks/(?:run\\?\"?\s+)?([\w.-]+\.py)")


def scripts_of(groups: list) -> set:
    found = set()
    for group in groups:
        for hook in group.get("hooks", []):
            found.update(HOOK_SCRIPT.findall(hook.get("command", "")))
    return found


def settings() -> None:
    dst = DEST / ".claude" / "settings.json"
    if not dst.exists():
        return
    try:
        mine = json.loads(dst.read_text(encoding="utf-8"))
        theirs = json.loads((SRC / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"  · .claude/settings.json no es JSON válido ({exc}); no se toca: revisa los hooks a mano")
        return
    added = []
    hooks = mine.setdefault("hooks", {})
    for event, groups in theirs.get("hooks", {}).items():
        have = scripts_of(hooks.get(event, []))
        for group in groups:
            missing = scripts_of([group]) - have
            if missing:
                hooks.setdefault(event, []).append(group)
                have |= missing
                added += [f"{event}:{s}" for s in sorted(missing)]
    if added:
        dst.write_text(json.dumps(mine, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  ✓ .claude/settings.json (hooks nuevos: {', '.join(added)})")


def gitignore() -> None:
    src_lines = (SRC / ".gitignore").read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, ln in enumerate(src_lines) if ln.startswith("# --- Harness"))
    except StopIteration:
        return
    block = []
    for ln in src_lines[start + 1:]:
        if not ln.strip():
            break
        block.append(ln)
    dst = DEST / ".gitignore"
    have = set(dst.read_text(encoding="utf-8").splitlines()) if dst.exists() else set()
    missing = [ln for ln in block if ln not in have]
    if missing:
        with open(dst, "a", encoding="utf-8") as fh:
            fh.write("\n# --- Harness (añadido al actualizar)\n" + "\n".join(missing) + "\n")
        print(f"  ✓ .gitignore (+{len(missing)} entradas del harness)")


if __name__ == "__main__":
    agents()
    settings()
    gitignore()
    sys.exit(0)
