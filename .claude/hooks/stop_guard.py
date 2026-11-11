#!/usr/bin/env python3
"""Stop (sesión principal): si hay una feature activa y el producto ha cambiado
después de la última nota del orquestador, pide dejar el próximo paso por escrito.
Así una sesión interrumpida —o un contexto compactado— se retoma sin adivinar."""
from __future__ import annotations

import sys

import _hx
from _hx import core

SLACK_SECONDS = 60


def newest_mtime(cfg) -> float:
    newest = 0.0
    for pkg in core.package_dirs(cfg):
        top = _hx.PROJECT / pkg
        if not top.exists():
            continue
        for path in top.rglob("*"):
            if path.is_file() and "node_modules" not in path.parts:
                newest = max(newest, path.stat().st_mtime)
    return newest


def main() -> None:
    event = _hx.read_event()
    if event.get("stop_hook_active") or event.get("agent_type") not in (None, "", _hx.MAIN_ROLE):
        return
    feat = core.active_feature(base=_hx.PROJECT)
    if not feat:
        return
    cfg = core.load_config(_hx.PROJECT)
    notes = _hx.PROJECT / "progress" / feat["id"] / "notes.md"
    notes_time = notes.stat().st_mtime if notes.exists() else 0.0
    if newest_mtime(cfg) <= notes_time + SLACK_SECONDS:
        return
    print(f"[harness:handoff] {feat['id']} está en '{feat['status']}' y el código ha cambiado desde tu última "
          f"nota. Antes de parar, añade a progress/{feat['id']}/notes.md 2-4 líneas: qué se ha hecho, qué "
          "decisión se tomó y cuál es el PRÓXIMO PASO exacto (`./hx status` te lo dice). Luego termina.",
          file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    _hx.safe_main(main)
