#!/usr/bin/env python3
"""PreToolUse (lectura, búsqueda, delegación, web, conectores): deja constancia de QUÉ hace cada agente
para el visor. No decide nada y nunca bloquea. Bash lo registra guard_bash, solo si el comando pasa."""
from __future__ import annotations

import _hx
from _hx import core
from activity_lib import describe


def main() -> None:
    event = _hx.read_event()
    if event.get("tool_name") in ("Bash", "PowerShell"):
        return
    info = describe(event)
    if not info:
        return
    kind = info.pop("kind")
    core.log_event(kind, base=_hx.PROJECT, role=_hx.role_of(event), feature=_hx._active_id(), **info)


if __name__ == "__main__":
    _hx.safe_main(main)
