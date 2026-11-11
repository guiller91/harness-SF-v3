#!/usr/bin/env python3
"""SubagentStart: registra el inicio (para exigir después un informe posterior a él)
e inyecta al subagente el contexto de la feature activa, para que no dependa de
que el orquestador se acuerde de pasárselo."""
from __future__ import annotations

import json
import time

import _hx
from _hx import core


def main() -> None:
    event = _hx.read_event()
    role = event.get("agent_type") or ""
    agent_id = event.get("agent_id") or "unknown"
    run_dir = _hx.PROJECT / core.RUN_DIR
    run_dir.mkdir(parents=True, exist_ok=True)
    core.write_json(run_dir / f"{agent_id}.json", {"role": role, "started": time.time(), "blocks": 0})

    roles = core.load_roles(_hx.PROJECT)
    spec = roles["roles"].get(role)
    feat = core.active_feature(base=_hx.PROJECT)
    if not spec:
        return
    cfg = core.load_config(_hx.PROJECT)
    core.log_event("subagent_start", base=_hx.PROJECT, role=role, feature=feat["id"] if feat else None)
    if not feat:
        ctx = ("[harness] No hay feature activa. Trabaja en SOLO LECTURA: cualquier escritura de producto "
               "será bloqueada.")
    else:
        fid, phase = feat["id"], feat["status"]
        lines = [f"[harness] Feature activa {fid} — {feat['title']} · fase {phase} · "
                 f"org de desarrollo `{cfg['org']['targetOrgAlias']}` (la única que puedes tocar).",
                 f"Diseño: docs/specs/{fid}/ · informes previos: progress/{fid}/ · estado: `./hx status`."]
        if phase not in spec.get("phases", []):
            lines.append(f"AVISO: tu rol trabaja en fase {'/'.join(spec['phases'])} y la feature está en "
                         f"'{phase}'. No podrás escribir producto; limítate a leer y a informar.")
        art = spec.get("artifact")
        if art:
            lines.append(f"Entregable obligatorio: {art['path'].replace('{fid}', fid)} con las secciones: "
                         f"{', '.join(art['headings'])}.")
        if spec["class"] != "design":
            heads = roles["reportHeadings"].get(spec["class"], [])
            lines.append(f"Informe obligatorio: progress/{fid}/{role}.md con las secciones: {', '.join(heads)}.")
        if spec["class"] == "build":
            scope = feat.get("scope", {}).get("files", [])
            lines.append("Scope aprobado (no escribas fuera): " + (", ".join(scope) or "(vacío)"))
        if spec["class"] == "review":
            lines.append(f"Al terminar registra tu veredicto: `./hx verdict {role} pass|fail --note \"...\"`. "
                         "Sin veredicto registrado no podrás terminar.")
        lines.append("No podrás dar por terminado tu turno sin esos entregables: el harness lo comprueba.")
        ctx = "\n".join(lines)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": ctx}},
                     ensure_ascii=False))


if __name__ == "__main__":
    _hx.safe_main(main)
