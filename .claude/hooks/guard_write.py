#!/usr/bin/env python3
"""PreToolUse (Write | Edit | MultiEdit | NotebookEdit).

Aplica, antes de que se escriba nada:
  1. rutas protegidas del harness  → deny
  2. configuración sensible        → ask (confirmación humana)
  3. producto: propiedad por rol + fase + scope de la feature → deny si no cuadra
  4. secretos en el contenido      → deny
"""
from __future__ import annotations

import _hx
from _hx import core


def main() -> None:
    event = _hx.read_event()
    if _hx.maintenance():
        return
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return
    relp = core.rel(file_path, _hx.PROJECT)
    if relp is None:
        return  # fuera del proyecto: decide el sistema de permisos de Claude Code

    role = _hx.role_of(event)
    decision, rule, reason = _hx.Policy().check_write(role, relp)
    if decision == "deny":
        _hx.deny(reason, rule, event)

    content = "\n".join(str(tool_input.get(k) or "") for k in ("content", "new_string", "new_source"))
    for edit in tool_input.get("edits") or []:
        content += "\n" + str(edit.get("new_string") or "")
    secret = _hx.find_secret(content)
    if secret:
        _hx.deny(f"El contenido incluye {secret}. Los secretos no van al repositorio: usa Named Credentials / "
                 "External Credentials, Custom Metadata protegido o variables de entorno del pipeline.",
                 "secret", event)

    if decision == "ask":
        _hx.ask(reason, rule, event)


if __name__ == "__main__":
    _hx.safe_main(main)
