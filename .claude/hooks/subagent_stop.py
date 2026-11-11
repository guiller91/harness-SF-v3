#!/usr/bin/env python3
"""SubagentStop: contrato de traspaso. Un subagente no puede terminar sin dejar en
disco su entregable (y, si es revisor, su veredicto registrado). Lo que no está en
disco no existe para el siguiente agente."""
from __future__ import annotations

import sys
import time

import _hx
from _hx import core

MAX_BLOCKS = 2


def main() -> None:
    event = _hx.read_event()
    role = event.get("agent_type") or ""
    agent_id = event.get("agent_id") or "unknown"
    roles = core.load_roles(_hx.PROJECT)
    spec = roles["roles"].get(role)
    feat = core.active_feature(base=_hx.PROJECT)
    if not spec or not feat or spec["class"] == "orchestrator":
        return
    fid, phase = feat["id"], feat["status"]
    if phase not in spec.get("phases", []):
        return

    run_file = _hx.PROJECT / core.RUN_DIR / f"{agent_id}.json"
    run = core.read_json(run_file, default={"started": 0, "blocks": 0})
    started = float(run.get("started") or 0) - 2

    def fresh(path) -> bool:
        return path.exists() and path.stat().st_mtime >= started

    problems = []
    art = spec.get("artifact")
    if art:
        path = _hx.PROJECT / art["path"].replace("{fid}", fid)
        relp = path.relative_to(_hx.PROJECT)
        if not path.exists():
            problems.append(f"falta tu entregable `{relp}`")
        else:
            miss = core.missing_headings(path, art["headings"])
            if miss:
                problems.append(f"`{relp}` no tiene las secciones: {', '.join(miss)}")
            elif not fresh(path):
                problems.append(f"`{relp}` no se ha actualizado en esta ejecución")
    if spec["class"] != "design":
        rep = core.report_path(fid, role, _hx.PROJECT)
        relp = rep.relative_to(_hx.PROJECT)
        heads = roles["reportHeadings"].get(spec["class"], [])
        if not rep.exists():
            problems.append(f"falta tu informe `{relp}` (secciones: {', '.join(heads)})")
        else:
            miss = core.missing_headings(rep, heads)
            if miss:
                problems.append(f"a `{relp}` le faltan las secciones: {', '.join(miss)}")
            elif not fresh(rep):
                problems.append(f"`{relp}` es de una ejecución anterior: actualízalo con lo hecho ahora")
    if spec["class"] == "review":
        ev_file = core.evidence_dir(fid, _hx.PROJECT) / f"review-{role}.json"
        if not fresh(ev_file):
            problems.append(f"no has registrado tu veredicto: `./hx verdict {role} pass|fail --note \"...\"`")

    if not problems:
        core.log_event("subagent_stop", base=_hx.PROJECT, role=role, feature=fid,
                       duration_s=round(time.time() - float(run.get("started") or time.time()), 1))
        return
    blocks = int(run.get("blocks") or 0)
    if blocks >= MAX_BLOCKS:
        core.log_event("handoff_incomplete", base=_hx.PROJECT, role=role, feature=fid, problems=problems)
        return  # no bucles infinitos: el orquestador verá el hueco en `./hx status`
    run["blocks"] = blocks + 1
    core.write_json(run_file, run)
    print("[harness:handoff] No puedes terminar todavía:\n  - " + "\n  - ".join(problems)
          + "\nComplétalo y termina. Sé concreto: comandos ejecutados, resultados reales, ficheros tocados.",
          file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    _hx.safe_main(main)
