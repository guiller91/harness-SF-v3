#!/usr/bin/env python3
"""hx - CLI del harness.

Es la ÚNICA vía para cambiar el estado de una feature. Los agentes no editan
`feature_list.json` ni la evidencia: piden la transición aquí y la CLI la concede
solo si las precondiciones se cumplen con evidencia del árbol de fuente actual.

    ./hx status            estado y siguiente paso
    ./hx propose <draft>   registra un borrador de feature (draft)
    ./hx approve <id>      [HUMANO] aprueba la feature (o su diseño)
    ./hx start <id>        abre la feature (design)
    ./hx scope <id> set|add <glob>...
    ./hx plan [id]         roles, gates y reviews que exige el cambio
    ./hx advance [id]      pasa a la fase siguiente si se cumplen los criterios
    ./hx gate run <gate|all>
    ./hx verdict <rol> pass|fail [--note ...]
    ./hx rework <id> --reason ...
    ./hx block <id> --reason ... | ./hx unblock <id>
    ./hx close <id>        [HUMANO] cierra la feature (done)
    ./hx metrics | doctor | check | tree-hash
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import core  # noqa: E402
from lib.core import HarnessError  # noqa: E402

OK, KO, WARN, DOT = "[OK]", "[X]", "[!]", "."
FEATURE_TYPES = ["feature", "bugfix", "refactor", "chore"]
SIZES = ["S", "M", "L"]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def out(msg: str = "") -> None:
    print(msg)


def actor() -> str:
    return os.environ.get("HX_ACTOR") or "cli"


def transition(feat: Dict[str, Any], to: str, note: str = "") -> None:
    frm = feat.get("status")
    feat["status"] = to
    feat.setdefault("history", []).append({"at": core.now(), "from": frm, "to": to, "note": note})
    core.log_event("transition", feature=feat["id"], frm=frm, to=to, note=note)


def slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:40] or "feature"


def resolve(features: List[Dict[str, Any]], fid: Optional[str]) -> Dict[str, Any]:
    if fid:
        return core.find_feature(features, fid)
    act = core.active_feature(features)
    if not act:
        raise HarnessError("No hay feature activa; indica un id.")
    return act


def plan_for(feat: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Set[str]]:
    """Plan derivado del cambio.

    - Antes de construir: de los tipos que anuncia el scope.
    - En build: scope ∪ cambios reales (lo planificado y no construido sigue exigiéndose).
    - En verify/release: de lo que realmente cambió.
    """
    pipeline = core.load_pipeline()
    scope = core.expand_pkg(feat.get("scope", {}).get("files", []), cfg)
    planned = core.kinds_of_scope(scope)
    phase = feat.get("status")
    if phase in ("draft", "approved", "design"):
        kinds = planned
    else:
        changed = core.kinds_of(core.product_changes(feat, cfg))
        kinds = (planned | changed) if phase == "build" else (changed or planned)
    return core.derive_plan(kinds, feat.get("size", "M"), pipeline), kinds - {"other"}


def role_artifact(role: str, fid: str, roles: Dict[str, Any]) -> Optional[Tuple[Path, List[str]]]:
    art = roles["roles"].get(role, {}).get("artifact")
    if not art:
        return None
    return core.root() / art["path"].replace("{fid}", fid), art.get("headings", [])


def check_role_output(role: str, fid: str, roles: Dict[str, Any]) -> List[str]:
    """Problemas con la salida obligatoria de un rol (artefacto y/o informe)."""
    problems: List[str] = []
    spec = roles["roles"].get(role)
    if not spec:
        return [f"rol desconocido: {role}"]
    art = role_artifact(role, fid, roles)
    if art:
        path, heads = art
        if not path.exists():
            problems.append(f"falta {path.relative_to(core.root())}")
        else:
            miss = core.missing_headings(path, heads)
            if miss:
                problems.append(f"{path.relative_to(core.root())} sin secciones: {', '.join(miss)}")
    if spec["class"] != "design":
        rep = core.report_path(fid, role)
        heads = roles["reportHeadings"].get(spec["class"], [])
        if not rep.exists():
            problems.append(f"falta el informe {rep.relative_to(core.root())}")
        else:
            miss = core.missing_headings(rep, heads)
            if miss:
                problems.append(f"{rep.relative_to(core.root())} sin secciones: {', '.join(miss)}")
    return problems


# --------------------------------------------------------------------------- #
# progress/current.md - lo regenera la CLI; es estado, no prosa
# --------------------------------------------------------------------------- #

def render_current(features: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    path = core.root() / "progress" / "current.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Sesión actual", "",
             "> Generado por `./hx`. No lo edites: las notas libres van en `progress/<id>/notes.md`.", ""]
    act = core.active_feature(features)
    if not act:
        pend = [f for f in features if f["status"] in ("draft", "approved", "blocked")]
        lines.append("**Estado:** sin feature activa.")
        if pend:
            lines += ["", "## En cola"]
            lines += [f"- `{f['id']}` [{f['status']}] {f['title']}" for f in pend]
    else:
        lines += status_lines(act, cfg, markdown=True)
    lines.append("")
    lines.append(f"_Actualizado: {core.now()}_")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def status_lines(feat: Dict[str, Any], cfg: Dict[str, Any], markdown: bool = False) -> List[str]:
    fid, phase = feat["id"], feat["status"]
    roles = core.load_roles()
    tree = core.tree_hash(cfg)
    plan, kinds = plan_for(feat, cfg)
    h = "## " if markdown else ""
    lines = [f"{h}Feature activa: {fid} - {feat['title']}",
             f"- Fase: **{phase}** . tamaño {feat.get('size', 'M')} . rework {feat.get('rework_count', 0)}"
             f" . árbol `{tree}`",
             f"- Tipos de cambio: {', '.join(sorted(kinds)) or '(sin metadata de producto)'}"]

    def mark(problems: List[str]) -> str:
        return OK if not problems else KO

    if phase == "design":
        lines.append("- Diseño:")
        for role in plan["design"]:
            probs = check_role_output(role, fid, roles)
            lines.append(f"  - {mark(probs)} {role}" + (f" - {'; '.join(probs)}" if probs else ""))
        scope = feat.get("scope", {}).get("files", [])
        lines.append(f"  - {OK if scope else KO} scope.files ({len(scope)} patrones)")
        if needs_design_approval(feat, cfg):
            lines.append(f"  - {OK if feat.get('design_approved_at') else KO} aprobación humana del diseño")
    if phase == "build":
        lines.append("- Construcción (en serie, en este orden):")
        for role in plan["build"]:
            probs = check_role_output(role, fid, roles)
            lines.append(f"  - {mark(probs)} {role}" + (f" - {'; '.join(probs)}" if probs else ""))
        stray = out_of_scope(feat, cfg)
        if stray:
            lines.append(f"  - {KO} fuera de scope: {', '.join(stray[:8])}")
    if phase in ("verify", "release"):
        lines.append("- Gates:")
        for gate in plan["gates"]:
            st, det = core.evidence_status(fid, f"gate-{gate}", tree)
            lines.append(f"  - {OK if st == 'pass' else KO} {gate}: {st}" + (f" - {det}" if det else ""))
        lines.append("- Reviews (solo lectura, en paralelo):")
        for role in plan["reviews"]:
            st, det = core.evidence_status(fid, f"review-{role}", tree)
            lines.append(f"  - {OK if st == 'pass' else KO} {role}: {st}" + (f" - {det}" if det else ""))
    if phase == "release":
        lines.append("- Entrega:")
        for role in plan["release"]:
            probs = check_role_output(role, fid, roles)
            lines.append(f"  - {mark(probs)} {role}" + (f" - {'; '.join(probs)}" if probs else ""))
        for gate in plan["release_gates"]:
            st, det = core.evidence_status(fid, f"gate-{gate}", tree)
            lines.append(f"  - {OK if st == 'pass' else KO} {gate}: {st}" + (f" - {det}" if det else ""))
    lines.append(f"- Siguiente paso: {next_step(feat, cfg, plan)}")
    return lines


def next_step(feat: Dict[str, Any], cfg: Dict[str, Any], plan: Dict[str, List[str]]) -> str:
    fid, phase = feat["id"], feat["status"]
    roles = core.load_roles()
    tree = core.tree_hash(cfg)
    if phase == "design":
        for role in plan["design"]:
            if check_role_output(role, fid, roles):
                return f"delegar en `{role}`"
        if not feat.get("scope", {}).get("files"):
            return f"fijar el scope con `./hx scope {fid} set <globs del mapa de archivos>`"
        if needs_design_approval(feat, cfg) and not feat.get("design_approved_at"):
            return f"enseñar el diseño al humano y pedir `./hx approve {fid}`"
        return f"`./hx advance {fid}` (> build)"
    if phase == "build":
        for role in plan["build"]:
            if check_role_output(role, fid, roles):
                return f"delegar en `{role}` (uno cada vez)"
        if out_of_scope(feat, cfg):
            return "resolver los cambios fuera de scope (revertir o `./hx scope add` justificado)"
        return f"`./hx advance {fid}` (> verify)"
    if phase == "verify":
        bad_gates = [g for g in plan["gates"] if core.evidence_status(fid, f"gate-{g}", tree)[0] != "pass"]
        failed = [g for g in bad_gates if core.evidence_status(fid, f"gate-{g}", tree)[0] == "fail"]
        if failed:
            return f"gate en rojo ({', '.join(failed)}): `./hx rework {fid} --reason ...` y volver al implementer"
        if bad_gates:
            return f"`./hx gate run all` (pendientes: {', '.join(bad_gates)})"
        bad_rev = [r for r in plan["reviews"] if core.evidence_status(fid, f"review-{r}", tree)[0] != "pass"]
        rejected = [r for r in bad_rev if core.evidence_status(fid, f"review-{r}", tree)[0] == "fail"]
        if rejected:
            return f"review rechazada ({', '.join(rejected)}): `./hx rework {fid} --reason ...`"
        if bad_rev:
            return f"lanzar EN PARALELO: {', '.join(bad_rev)}"
        return f"`./hx advance {fid}` (> release)"
    if phase == "release":
        for role in plan["release"]:
            if check_role_output(role, fid, roles):
                return f"delegar en `{role}`"
        bad = [g for g in plan["release_gates"] if core.evidence_status(fid, f"gate-{g}", tree)[0] != "pass"]
        if bad:
            return f"`./hx gate run {bad[0]}`"
        return f"resumir al humano y pedir `./hx close {fid}`"
    return "-"


def needs_design_approval(feat: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    return feat.get("size", "M") in cfg["workflow"].get("designApprovalForSizes", [])


def out_of_scope(feat: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    scope = core.expand_pkg(feat.get("scope", {}).get("files", []), cfg)
    return [f for f in core.product_changes(feat, cfg) if not core.match_any(f, scope)]


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #

def cmd_status(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    act = core.active_feature(features)
    if args.json:
        payload: Dict[str, Any] = {"active": act["id"] if act else None,
                                   "features": [{k: f.get(k) for k in ("id", "title", "status", "size")}
                                                for f in features]}
        if act:
            plan, kinds = plan_for(act, cfg)
            payload.update(phase=act["status"], plan=plan, kinds=sorted(kinds),
                           tree_hash=core.tree_hash(cfg), next=next_step(act, cfg, plan))
        out(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    org = cfg["org"]
    out(f"Proyecto: {cfg['project']} . org {org['model']} > '{org['targetOrgAlias']}'")
    if act:
        out("\n".join(status_lines(act, cfg)))
    else:
        out("Sin feature activa.")
    rest = [f for f in features if not act or f["id"] != act["id"]]
    if rest and not args.brief:
        out("Otras features:")
        for f in rest:
            extra = f" - {f.get('blocked_reason')}" if f["status"] == "blocked" else ""
            out(f"  {f['id']} [{f['status']}] {f['title']}{extra}")
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    draft_path = Path(args.draft)
    draft = core.read_json(draft_path)
    if not isinstance(draft, dict):
        raise HarnessError("El borrador debe ser un objeto JSON.")
    errors: List[str] = []
    for key in ("title", "description"):
        if not isinstance(draft.get(key), str) or not draft[key].strip():
            errors.append(f"'{key}' es obligatorio")
    ftype = draft.get("type", "feature")
    if ftype not in FEATURE_TYPES:
        errors.append(f"'type' debe ser uno de {FEATURE_TYPES}")
    size = draft.get("size", "M")
    if size not in SIZES:
        errors.append(f"'size' debe ser uno de {SIZES}")
    raw_ac = draft.get("acceptance_criteria") or []
    acs: List[Dict[str, str]] = []
    for item in raw_ac:
        text = item.get("text") if isinstance(item, dict) else item
        if isinstance(text, str) and text.strip():
            acs.append({"id": f"AC-{len(acs) + 1}", "text": text.strip()})
    if not acs:
        errors.append("hace falta al menos un criterio de aceptación verificable")
    features = core.load_features()
    known = {f["id"] for f in features}
    deps = draft.get("depends_on") or []
    for dep in deps:
        if dep not in known:
            errors.append(f"depends_on: no existe {dep}")
    scope_files = (draft.get("scope") or {}).get("files") or []
    if not isinstance(scope_files, list):
        errors.append("'scope.files' debe ser una lista de globs")
    if errors:
        raise HarnessError("Borrador inválido:\n  - " + "\n  - ".join(errors))
    nums = [int(m.group(1)) for f in features if (m := re.match(r"F-(\d+)$", f.get("id", "")))]
    fid = f"F-{(max(nums) + 1 if nums else 1):03d}"
    feat = {
        "id": fid, "title": draft["title"].strip(), "description": draft["description"].strip(),
        "type": ftype, "size": size, "priority": draft.get("priority", "medium"),
        "status": "draft", "acceptance_criteria": acs,
        "scope": {"files": scope_files}, "out_of_scope": draft.get("out_of_scope") or [],
        "depends_on": deps, "notes": draft.get("notes", ""),
        "created_at": core.now(), "rework_count": 0,
        "history": [{"at": core.now(), "from": None, "to": "draft", "note": "propuesta"}],
    }
    features.append(feat)
    core.save_features(features)
    core.log_event("propose", feature=fid, size=size, type=ftype)
    render_current(features, core.load_config())
    out(f"{OK} Registrada {fid} como BORRADOR. Enséñasela al humano tal cual:\n")
    out(f"  {fid} - {feat['title']}  [{ftype}, tamaño {size}]")
    out(f"  {feat['description']}")
    for ac in acs:
        out(f"    {ac['id']}: {ac['text']}")
    if feat["out_of_scope"]:
        out("  Fuera de alcance: " + "; ".join(feat["out_of_scope"]))
    out(f"\nCuando dé el OK: ./hx approve {fid}   (pide confirmación al humano)")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    if feat["status"] == "draft":
        feat["approved_at"] = core.now()
        transition(feat, "approved", "aprobada por el humano")
        msg = f"{OK} {feat['id']} aprobada. Ábrela con ./hx start {feat['id']}"
    elif feat["status"] == "design":
        feat["design_approved_at"] = core.now()
        core.log_event("design_approved", feature=feat["id"])
        msg = f"{OK} Diseño de {feat['id']} aprobado."
    else:
        raise HarnessError(f"{feat['id']} está en '{feat['status']}'; solo se aprueba un borrador o un diseño.")
    core.save_features(features)
    render_current(features, core.load_config())
    out(msg)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    if feat["status"] != "approved":
        raise HarnessError(f"{feat['id']} está en '{feat['status']}'; debe estar 'approved' (./hx approve).")
    act = core.active_feature(features)
    if act:
        raise HarnessError(f"Ya hay una feature activa ({act['id']}, {act['status']}). Una cada vez.")
    pending = [d for d in feat.get("depends_on", []) if core.find_feature(features, d)["status"] != "done"]
    if pending:
        raise HarnessError(f"Dependencias sin cerrar: {', '.join(pending)}")
    rc, head = core.git(["rev-parse", "HEAD"])
    feat["base_commit"] = head if rc == 0 and head else None
    if feat["base_commit"] and not args.no_branch:
        branch = f"{cfg['git']['featureBranchPrefix']}{feat['id']}-{slug(feat['title'])}"
        rc, current = core.git(["rev-parse", "--abbrev-ref", "HEAD"])
        if current != branch:
            rc, _ = core.git(["checkout", "-b", branch])
            if rc != 0:
                rc, _ = core.git(["checkout", branch])
        if rc == 0:
            feat["branch"] = branch
        else:
            out(f"{WARN} No pude crear la rama {branch}; sigo en la actual.")
    feat["started_at"] = core.now()
    transition(feat, "design", "inicio")
    core.save_features(features)
    (core.root() / "progress" / feat["id"]).mkdir(parents=True, exist_ok=True)
    core.spec_dir(feat["id"]).mkdir(parents=True, exist_ok=True)
    notes = core.root() / "progress" / feat["id"] / "notes.md"
    if not notes.exists():
        notes.write_text(f"# Notas - {feat['id']} {feat['title']}\n\n"
                         "Decisiones, contexto y próximo paso. Lo mantiene el orquestador.\n", encoding="utf-8")
    render_current(features, cfg)
    out(f"{OK} {feat['id']} en fase design" + (f" (rama {feat['branch']})" if feat.get("branch") else ""))
    out("\n".join(status_lines(feat, cfg)))
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    if feat["status"] not in ("draft", "approved", "design", "build"):
        raise HarnessError(f"No se cambia el scope en fase '{feat['status']}'. Usa ./hx rework si hace falta.")
    for pat in args.globs:
        body = pat[1:] if pat.startswith("!") else pat
        if body.startswith("/") or ".." in body.split("/"):
            raise HarnessError(f"Patrón inválido: {pat}")
        if not any(core.in_package(p.replace("**", "x").replace("*", "x"), cfg)
                   for p in core.expand_pkg([body], cfg)):
            raise HarnessError(f"'{pat}' no apunta a un packageDir ({', '.join(core.package_dirs(cfg))}). "
                               "El scope solo cubre metadata de producto.")
        if not pat.startswith("!") and not args.allow_unclassified and all(
                core.classify_glob(p) == "other" for p in core.expand_pkg([body], cfg)):
            raise HarnessError(
                f"'{pat}' es demasiado amplio o de un tipo que el harness no reconoce: no permite derivar "
                "qué roles y gates exige. Usa las rutas del mapa de archivos del diseño (p. ej. "
                "'force-app/**/classes/Pedido*'). Si de verdad es un tipo de metadata sin rol asignado, "
                "repite con --allow-unclassified.")
    files = feat.setdefault("scope", {}).setdefault("files", [])
    if args.action == "set":
        files[:] = list(dict.fromkeys(args.globs))
    else:
        if feat["status"] == "build" and not args.reason:
            raise HarnessError("Ampliar el scope en build exige --reason (queda registrado como scope creep).")
        files.extend(g for g in args.globs if g not in files)
    core.log_event("scope_change", feature=feat["id"], action=args.action, phase=feat["status"],
                   globs=args.globs, reason=args.reason or "")
    core.save_features(features)
    render_current(features, cfg)
    out(f"{OK} scope de {feat['id']}: {len(files)} patrones")
    for pat in files:
        out(f"   {pat}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = resolve(features, args.id)
    plan, kinds = plan_for(feat, cfg)
    if args.json:
        out(json.dumps({"feature": feat["id"], "kinds": sorted(kinds), "plan": plan}, indent=2))
        return 0
    out(f"Plan de {feat['id']} (tamaño {feat.get('size', 'M')}; tipos: {', '.join(sorted(kinds)) or 'ninguno'})")
    labels = [("design", "Diseño"), ("build", "Construcción (EN SERIE, en este orden)"),
              ("gates", "Gates de verificación"), ("reviews", "Reviews (solo lectura, EN PARALELO)"),
              ("release", "Entrega"), ("release_gates", "Gates de entrega")]
    for key, label in labels:
        out(f"  {label}: {' > '.join(plan[key]) if key == 'build' else ', '.join(plan[key]) or '-'}")
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = resolve(features, args.id)
    fid, phase = feat["id"], feat["status"]
    roles = core.load_roles()
    problems: List[str] = []

    if phase == "design":
        plan, _ = plan_for(feat, cfg)
        for role in plan["design"]:
            problems += check_role_output(role, fid, roles)
        if not feat.get("scope", {}).get("files"):
            problems.append("scope.files vacío: fíjalo con ./hx scope set a partir del mapa de archivos")
        if needs_design_approval(feat, cfg) and not feat.get("design_approved_at"):
            problems.append(f"tamaño {feat['size']}: el diseño necesita aprobación humana (./hx approve {fid})")
        target = "build"

    elif phase == "build":
        plan, kinds = plan_for(feat, cfg)
        changed = core.product_changes(feat, cfg)
        if not changed and feat.get("type") != "chore":
            problems.append("no hay cambios de producto respecto al commit base")
        stray = out_of_scope(feat, cfg)
        if stray:
            problems.append("cambios fuera de scope: " + ", ".join(stray[:10]))
        for role in plan["build"]:
            problems += check_role_output(role, fid, roles)
        target = "verify"

    elif phase == "verify":
        plan, _ = plan_for(feat, cfg)
        tree = core.tree_hash(cfg)
        for gate in plan["gates"]:
            st, det = core.evidence_status(fid, f"gate-{gate}", tree)
            if st != "pass":
                problems.append(f"gate {gate}: {st}" + (f" ({det})" if det else ""))
        for role in plan["reviews"]:
            st, det = core.evidence_status(fid, f"review-{role}", tree)
            if st != "pass":
                problems.append(f"review {role}: {st}" + (f" ({det})" if det else ""))
            problems += check_role_output(role, fid, roles)
        acc = core.spec_dir(fid) / "acceptance.md"
        if acc.exists():
            text = acc.read_text(encoding="utf-8", errors="replace")
            miss = [ac["id"] for ac in feat.get("acceptance_criteria", [])
                    if not re.search(rf"\b{re.escape(ac['id'])}\b", text)]
            if miss:
                problems.append(f"acceptance.md no traza: {', '.join(miss)}")
            if re.search(r"\|\s*(FAIL|NO VERIFICADO)\s*\|", text, re.I):
                problems.append("acceptance.md tiene criterios en FAIL / NO VERIFICADO")
        target = "release"

    elif phase == "release":
        raise HarnessError(f"La fase release se cierra con ./hx close {fid} (requiere confirmación humana).")
    else:
        raise HarnessError(f"{fid} está en '{phase}': nada que avanzar.")

    if problems:
        core.log_event("advance_denied", feature=fid, phase=phase, problems=problems)
        out(f"{KO} {fid} NO puede pasar de {phase} a {target}:")
        for p in dict.fromkeys(problems):
            out(f"   - {p}")
        return 1
    transition(feat, target, "criterios de salida cumplidos")
    core.save_features(features)
    render_current(features, cfg)
    out(f"{OK} {fid}: {phase} > {target}")
    out("\n".join(status_lines(feat, cfg)))
    return 0


def cmd_rework(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    if feat["status"] not in ("verify", "release"):
        raise HarnessError(f"rework solo aplica en verify/release (ahora: {feat['status']}).")
    feat["rework_count"] = feat.get("rework_count", 0) + 1
    limit = cfg["workflow"]["maxReworkLoops"]
    core.log_event("rework", feature=feat["id"], count=feat["rework_count"], reason=args.reason)
    if feat["rework_count"] > limit:
        feat["blocked_from"] = "build"
        feat["blocked_reason"] = f"superado el máximo de {limit} ciclos de rework: {args.reason}"
        transition(feat, "blocked", feat["blocked_reason"])
        core.save_features(features)
        render_current(features, cfg)
        out(f"{KO} {feat['id']} BLOQUEADA: {limit} ciclos de rework agotados. Escala al humano; "
            "no sigas iterando. Probablemente el diseño o los criterios están mal.")
        return 2
    transition(feat, "build", f"rework #{feat['rework_count']}: {args.reason}")
    core.save_features(features)
    render_current(features, cfg)
    out(f"{OK} {feat['id']} vuelve a build (rework {feat['rework_count']}/{limit}). "
        "Delega la corrección en el implementer dueño del fichero; después repite gates y reviews.")
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    if feat["status"] in ("done", "blocked"):
        raise HarnessError(f"{feat['id']} está en '{feat['status']}'.")
    feat["blocked_from"] = feat["status"]
    feat["blocked_reason"] = args.reason
    transition(feat, "blocked", args.reason)
    core.save_features(features)
    render_current(features, core.load_config())
    out(f"{OK} {feat['id']} bloqueada: {args.reason}")
    return 0


def cmd_unblock(args: argparse.Namespace) -> int:
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    if feat["status"] != "blocked":
        raise HarnessError(f"{feat['id']} no está bloqueada.")
    back = feat.pop("blocked_from", "approved")
    if back in core.ACTIVE_PHASES and core.active_feature(features):
        raise HarnessError("Hay otra feature activa; ciérrala o bloquéala antes.")
    feat.pop("blocked_reason", None)
    if args.reset_rework:
        feat["rework_count"] = 0
    transition(feat, back, "desbloqueada")
    core.save_features(features)
    render_current(features, core.load_config())
    out(f"{OK} {feat['id']} vuelve a '{back}'")
    return 0


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #

def gate_names() -> List[str]:
    return sorted(p.stem for p in (core.root() / "harness" / "gates").glob("*.sh") if not p.name.startswith("_"))


def gate_script(name: str) -> Path:
    return core.root() / "harness" / "gates" / f"{name}.sh"


def run_gate(name: str, feat: Optional[Dict[str, Any]], cfg: Dict[str, Any]) -> int:
    script = gate_script(name)
    if name.startswith("_") or not script.exists():
        raise HarnessError(f"No existe el gate '{name}' ({script.relative_to(core.root())}).")
    fid = feat["id"] if feat else "_adhoc"
    evdir = core.evidence_dir(fid)
    evdir.mkdir(parents=True, exist_ok=True)
    log_path = evdir / f"gate-{name}.log"
    summary_path = evdir / f"gate-{name}.summary"
    changed_path = evdir / "changed-files.txt"
    if summary_path.exists():
        summary_path.unlink()
    changed = core.product_changes(feat, cfg) if feat else []
    with open(changed_path, "w", encoding="utf-8", newline="\n") as fh:  # LF siempre: en Windows write_text daría CRLF y bash leería "ruta\r"
        fh.write("\n".join(changed) + ("\n" if changed else ""))

    if feat and not changed and name in ("static", "apex-tests"):
        _, kinds = plan_for(feat, cfg)
        if kinds & {"apex", "apex-test", "lwc", "lwc-test"}:
            msg = ("la feature declara cambios de código pero no se detecta ningún fichero de producto "
                   "cambiado (¿base_commit, packageDirs o ficheros sin guardar?)")
            out(f"-- {KO} gate {name}: FAIL - {msg} --")
            core.write_evidence(fid, f"gate-{name}", {
                "kind": "gate", "name": name, "feature": fid, "status": "fail", "exit_code": 1,
                "tree_hash": core.tree_hash(cfg), "started_at": core.now(), "finished_at": core.now(),
                "duration_s": 0, "summary": msg, "log": "", "actor": actor()})
            return 1

    org, quality = cfg["org"], cfg["quality"]
    env = dict(os.environ)
    env.update({
        "HX_ROOT": str(core.root()),
        "HX_FEATURE": fid,
        "HX_PROJECT": str(cfg.get("project", "")),
        "HX_TARGET_ORG": org.get("targetOrgAlias", ""),
        "HX_VALIDATION_ORG": org.get("validationOrgAlias") or org.get("targetOrgAlias", ""),
        "HX_PKG_DIRS": " ".join(core.package_dirs(cfg)),
        "HX_COVERAGE_GATE": str(quality["coverageGatePerClass"]),
        "HX_TEST_LEVEL": quality["apexTestLevel"],
        "HX_SEVERITY": str(quality["analyzer"]["severityThreshold"]),
        "HX_RULE_SELECTORS": " ".join(quality["analyzer"]["ruleSelector"]),
        "HX_ANALYZER_CONFIG": quality["analyzer"].get("configFile", ""),
        "HX_ANALYZER_SCOPE": quality["analyzer"].get("scope", "changed"),
        "HX_EVIDENCE_DIR": str(evdir),
        "HX_CHANGED_FILES": str(changed_path),
        "HX_SUMMARY_FILE": str(summary_path),
        "HX_MANIFEST": str(core.root() / "manifest" / fid / "package.xml"),
        "HX_LIB": str(core.root() / "harness" / "lib"),
        "HX_PY": sys.executable,
    })
    tree_before = core.tree_hash(cfg)
    started, t0 = core.now(), time.time()
    out(f"-- gate {name} . {fid} . árbol {tree_before} --")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(["bash", str(script)], cwd=str(core.root()), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        rc = proc.wait()
    tree_after = core.tree_hash(cfg)
    summary = summary_path.read_text(encoding="utf-8").strip() if summary_path.exists() else ""
    status = "pass" if rc == 0 else "fail"
    if tree_after != tree_before:
        status, summary = "fail", "el árbol de fuente cambió durante el gate; repítelo"
    evidence = {
        "kind": "gate", "name": name, "feature": fid, "status": status, "exit_code": rc,
        "tree_hash": tree_after, "started_at": started, "finished_at": core.now(),
        "duration_s": round(time.time() - t0, 1), "summary": summary,
        "log": str(log_path.relative_to(core.root())), "actor": actor(),
    }
    core.write_evidence(fid, f"gate-{name}", evidence)
    core.log_event("gate", feature=fid, gate=name, status=status, duration_s=evidence["duration_s"])
    out(f"-- {OK if status == 'pass' else KO} gate {name}: {status.upper()}"
        + (f" - {summary}" if summary else "") + f" . log: {evidence['log']} --")
    return 0 if status == "pass" else 1


def cmd_gate(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    if args.action == "list":
        for name in gate_names():
            out(name)
        return 0
    feat = core.active_feature(features)
    if not feat and not args.adhoc:
        raise HarnessError("No hay feature activa. Para una ejecución suelta: ./hx gate run <gate> --adhoc")
    names: List[str]
    if args.name == "all":
        if not feat:
            raise HarnessError("'all' necesita una feature activa.")
        plan, _ = plan_for(feat, cfg)
        names = list(plan["gates"])
        if feat["status"] == "release":
            names += plan["release_gates"]
        if not names:
            out("Este cambio no exige gates.")
            return 0
    else:
        names = [args.name]
    worst = 0
    for name in names:
        worst = max(worst, run_gate(name, feat, cfg))
    if feat:
        render_current(features, cfg)
    return worst


def cmd_verdict(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = core.active_feature(features)
    if not feat:
        raise HarnessError("No hay feature activa.")
    if feat["status"] != "verify":
        raise HarnessError(f"Los veredictos se registran en fase verify (ahora: {feat['status']}).")
    roles = core.load_roles()
    spec = roles["roles"].get(args.role)
    if not spec or spec["class"] != "review":
        raise HarnessError(f"'{args.role}' no es un rol de review.")
    env_role = os.environ.get("HX_AGENT_TYPE")
    if env_role and env_role != args.role:
        raise HarnessError(f"Un '{env_role}' no puede registrar el veredicto de '{args.role}'.")
    problems = check_role_output(args.role, feat["id"], roles)
    if problems:
        raise HarnessError("Antes del veredicto, completa tu salida:\n  - " + "\n  - ".join(problems))
    rep = core.report_path(feat["id"], args.role)
    text = rep.read_text(encoding="utf-8", errors="replace")
    blockers = len(re.findall(r"^\s*[-*]\s*\[?(BLOQUEANTE|BLOCKER)\b", text, re.M | re.I))
    if args.result == "pass" and blockers:
        raise HarnessError(f"Tu informe lista {blockers} hallazgo(s) BLOQUEANTE(S): el veredicto no puede ser pass.")
    tree = core.tree_hash(cfg)
    core.write_evidence(feat["id"], f"review-{args.role}", {
        "kind": "review", "name": args.role, "feature": feat["id"], "status": args.result,
        "tree_hash": tree, "finished_at": core.now(), "summary": args.note or "",
        "blockers": blockers, "report": str(rep.relative_to(core.root())),
    })
    core.log_event("verdict", feature=feat["id"], role=args.role, status=args.result, blockers=blockers)
    render_current(features, cfg)
    out(f"{OK} veredicto de {args.role}: {args.result.upper()} (árbol {tree})")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    features = core.load_features()
    feat = core.find_feature(features, args.id)
    fid = feat["id"]
    if feat["status"] != "release":
        raise HarnessError(f"{fid} está en '{feat['status']}'; solo se cierra desde release.")
    roles = core.load_roles()
    plan, kinds = plan_for(feat, cfg)
    tree = core.tree_hash(cfg)
    problems: List[str] = []
    for role in plan["release"]:
        problems += check_role_output(role, fid, roles)
    if kinds and not (core.root() / "manifest" / fid / "package.xml").exists():
        problems.append(f"falta manifest/{fid}/package.xml")
    for gate in plan["gates"] + plan["release_gates"]:
        st, det = core.evidence_status(fid, f"gate-{gate}", tree)
        if st != "pass":
            problems.append(f"gate {gate}: {st}" + (f" ({det})" if det else ""))
    for role in plan["reviews"]:
        st, det = core.evidence_status(fid, f"review-{role}", tree)
        if st != "pass":
            problems.append(f"review {role}: {st}" + (f" ({det})" if det else ""))
    if problems:
        core.log_event("close_denied", feature=fid, problems=problems)
        out(f"{KO} {fid} NO se puede cerrar:")
        for p in dict.fromkeys(problems):
            out(f"   - {p}")
        return 1
    feat["closed_at"] = core.now()
    feat["closed_tree_hash"] = tree
    transition(feat, "done", "cerrada por el humano")
    core.save_features(features)
    append_history(feat, plan, tree, cfg)
    render_current(features, cfg)
    out(f"{OK} {fid} cerrada (done). Evidencia en .harness/evidence/{fid}/ . bitácora actualizada.")
    out("   Promoción a entornos superiores: por pipeline/humano con manifest/" + fid + "/ (ver docs/specs/"
        + fid + "/release.md). Los agentes no despliegan fuera de la org de desarrollo.")
    return 0


def append_history(feat: Dict[str, Any], plan: Dict[str, List[str]], tree: str, cfg: Dict[str, Any]) -> None:
    fid = feat["id"]
    path = core.root() / "progress" / "history.md"
    if not path.exists():
        path.write_text("# Bitácora (append-only)\n\nLa escribe `./hx close`. No se reescribe.\n", encoding="utf-8")
    lines = ["", "---", "", f"## [{fid}] {feat['title']} - {feat['closed_at']}",
             f"- **Tipo/tamaño:** {feat.get('type')} / {feat.get('size')} . **rework:** {feat.get('rework_count', 0)}"
             f" . **árbol verificado:** `{tree}`",
             f"- **Rama:** {feat.get('branch', '-')} . **base:** {feat.get('base_commit') or '-'}",
             "- **Criterios de aceptación:**"]
    lines += [f"  - {ac['id']}: {ac['text']}" for ac in feat.get("acceptance_criteria", [])]
    lines.append("- **Archivos de producto:**")
    lines += [f"  - `{f}`" for f in core.product_changes(feat, cfg)] or ["  - (ninguno)"]
    lines.append("- **Evidencia:**")
    for gate in plan["gates"] + plan["release_gates"]:
        ev = core.read_evidence(fid, f"gate-{gate}") or {}
        lines.append(f"  - gate `{gate}`: {ev.get('status', '?')} - {ev.get('summary', '')} (`{ev.get('log', '')}`)")
    for role in plan["reviews"]:
        ev = core.read_evidence(fid, f"review-{role}") or {}
        lines.append(f"  - review `{role}`: {ev.get('status', '?')} - `{ev.get('report', '')}`")
    lines.append(f"- **Diseño y entrega:** `docs/specs/{fid}/`")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #

def _parse(ts: str) -> float:
    import datetime as dt
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()


def _fmt(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


def feature_metrics(feat: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    fid = feat["id"]
    evs = [e for e in events if e.get("feature") == fid]
    phase_time: Dict[str, float] = {}
    hist = feat.get("history", [])
    for cur, nxt in zip(hist, hist[1:] + [None]):
        if cur["to"] in core.ACTIVE_PHASES:
            end = _parse(nxt["at"]) if nxt else time.time()
            phase_time[cur["to"]] = phase_time.get(cur["to"], 0) + (end - _parse(cur["at"]))
    gates = [e for e in evs if e["event"] == "gate"]
    verdicts = [e for e in evs if e["event"] == "verdict"]
    lead = None
    if feat.get("started_at") and feat.get("closed_at"):
        lead = _parse(feat["closed_at"]) - _parse(feat["started_at"])
    return {
        "id": fid, "title": feat["title"], "status": feat["status"], "size": feat.get("size"),
        "lead_time_s": lead, "phase_time_s": {k: round(v) for k, v in phase_time.items()},
        "gate_runs": len(gates), "gate_failures": sum(1 for g in gates if g["status"] != "pass"),
        "first_pass_gates": _first_pass(gates, "gate"),
        "reviews": len(verdicts), "review_rejections": sum(1 for v in verdicts if v["status"] != "pass"),
        "rework_loops": feat.get("rework_count", 0),
        "scope_changes_in_build": sum(1 for e in evs if e["event"] == "scope_change" and e.get("phase") == "build"),
        "blocked_actions": sum(1 for e in evs if e["event"] == "guard_block"),
        "advance_denied": sum(1 for e in evs if e["event"] in ("advance_denied", "close_denied")),
    }


def _first_pass(items: List[Dict[str, Any]], key: str) -> Optional[float]:
    first: Dict[str, str] = {}
    for it in items:
        first.setdefault(it[key], it["status"])
    if not first:
        return None
    return round(100.0 * sum(1 for s in first.values() if s == "pass") / len(first), 1)


def cmd_metrics(args: argparse.Namespace) -> int:
    features = core.load_features()
    events = core.read_events()
    rows = [feature_metrics(f, events) for f in features if f["status"] not in ("draft", "approved")]
    blocks = sum(1 for e in events if e["event"] == "guard_block")
    if args.json:
        out(json.dumps({"features": rows, "guard_blocks_total": blocks}, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        out("Aún no hay features iniciadas.")
        return 0
    out(f"{'ID':<7}{'Estado':<9}{'Tam':<4}{'Lead':<8}{'Gates(rojos)':<14}{'1ª pasada':<11}"
        f"{'Reviews(rech.)':<16}{'Rework':<8}{'Scope+':<7}Título")
    for r in rows:
        lead = _fmt(r["lead_time_s"]) if r["lead_time_s"] else "-"
        fp = f"{r['first_pass_gates']}%" if r["first_pass_gates"] is not None else "-"
        out(f"{r['id']:<7}{r['status']:<9}{r['size'] or '':<4}{lead:<8}"
            f"{str(r['gate_runs']) + ' (' + str(r['gate_failures']) + ')':<14}{fp:<11}"
            f"{str(r['reviews']) + ' (' + str(r['review_rejections']) + ')':<16}"
            f"{r['rework_loops']:<8}{r['scope_changes_in_build']:<7}{r['title'][:40]}")
    done = [r for r in rows if r["status"] == "done" and r["lead_time_s"]]
    if done:
        avg = sum(r["lead_time_s"] for r in done) / len(done)
        out(f"\nCerradas: {len(done)} . lead time medio {_fmt(avg)} . "
            f"rework medio {sum(r['rework_loops'] for r in done) / len(done):.1f}")
    out(f"Acciones bloqueadas por los guardas (total): {blocks}")
    return 0


# --------------------------------------------------------------------------- #
# doctor / check
# --------------------------------------------------------------------------- #

def _run(cmd: List[str], timeout: int = 90) -> Tuple[int, str]:
    try:
        # Resuelve "sf" a su ruta completa para evitar problemas de PATH en Windows
        if cmd and cmd[0] == "sf":
            sf_path = shutil.which("sf")
            if sf_path:
                cmd = [sf_path] + cmd[1:]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(core.root()))
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    org = cfg["org"]
    failed = False

    def ok(msg: str) -> None:
        out(f"  {OK} {msg}")

    def bad(msg: str) -> None:
        nonlocal failed
        failed = True
        out(f"  {KO} {msg}")

    def note(msg: str) -> None:
        out(f"  {DOT} {msg}")

    out("== hx doctor ==")
    out("[1] Herramientas")
    for tool, hint in (("git", "instala git"), ("node", "instala Node.js LTS"),
                       ("sf", "npm install -g @salesforce/cli")):
        ok(f"{tool} > {shutil.which(tool)}") if shutil.which(tool) else bad(f"falta {tool} ({hint})")
    if shutil.which("sf"):
        rc, txt = _run(["sf", "plugins"])
        ok("plugin code-analyzer") if "code-analyzer" in txt else bad(
            "falta Code Analyzer v5: sf plugins install code-analyzer")
    shim, bash = core.root() / "bin" / "sf", shutil.which("bash")
    if shim.exists() and bash:
        rc, txt = _run([bash, str(shim), "--version"])
        if rc == 0 and txt.strip():
            ok(f"sf desde bash (shim del harness): {txt.strip().splitlines()[-1][:70]}")
        else:
            bad("`sf` no funciona desde bash (bin/sf): " + (txt.strip().splitlines() or ['sin salida'])[-1][:100]
                + ". Instala la CLI con npm: npm install -g @salesforce/cli")
    ok("java (motores PMD/CPD/SFGE del analyzer)") if shutil.which("java") else note(
        "sin java: Code Analyzer no podrá ejecutar PMD/SFGE")
    rc, _ = core.git(["rev-parse", "--git-dir"])
    ok("repositorio git") if rc == 0 else bad("no es un repositorio git (git init && primer commit)")
    rc, _ = core.git(["rev-parse", "HEAD"])
    ok("hay commit base") if rc == 0 else bad("sin commits: el harness necesita un commit base para medir cambios")

    out("[2] Configuración")
    if cfg.get("project") in ("", "CHANGE_ME"):
        note("harness.config.json > 'project' sigue en CHANGE_ME")
    if org["model"] not in ("scratch", "sandbox"):
        bad(f"org.model inválido: {org['model']}")
    else:
        ok(f"org.model = {org['model']} . target '{org['targetOrgAlias']}'")
    if org["targetOrgAlias"] in org.get("protectedAliases", []):
        bad("targetOrgAlias está en protectedAliases")
    (ok if (core.root() / "sfdx-project.json").exists() else bad)("sfdx-project.json")
    for d in core.package_dirs(cfg):
        (ok if (core.root() / d).is_dir() else bad)(f"packageDir {d}/")

    out("[3] Integridad del harness")
    problems = integrity_problems()
    if problems:
        for p in problems:
            bad(p)
    else:
        ok("roles, pipeline, agentes, hooks y gates coherentes")
    try:
        features = core.load_features()
        core.active_feature(features)
        ok(f"feature_list.json ({len(features)} features)")
    except HarnessError as exc:
        bad(str(exc))

    if not args.offline and shutil.which("sf"):
        out("[4] Orgs")
        if org["model"] == "scratch":
            rc, _ = _run(["sf", "org", "display", "--target-org", org["devHubAlias"], "--json"])
            ok(f"DevHub '{org['devHubAlias']}' autenticado") if rc == 0 else bad(
                f"DevHub '{org['devHubAlias']}' sin autenticar: sf org login web --set-default-dev-hub "
                f"--alias {org['devHubAlias']}")
        rc, txt = _run(["sf", "org", "display", "--target-org", org["targetOrgAlias"], "--json"])
        if rc != 0:
            (note if org["model"] == "scratch" else bad)(
                f"org '{org['targetOrgAlias']}' no disponible"
                + (" (créala con ./hx org setup)" if org["model"] == "scratch" else " (sf org login web --alias ...)"))
        else:
            ok(f"org '{org['targetOrgAlias']}' accesible")
            rc, txt = _run(["sf", "data", "query", "--target-org", org["targetOrgAlias"], "--json",
                            "--query", "SELECT IsSandbox, OrganizationType FROM Organization LIMIT 1"])
            try:
                rec = json.loads(txt[txt.index("{"):])["result"]["records"][0]
                if rec.get("IsSandbox") or org["model"] == "scratch":
                    ok("la org objetivo NO es producción")
                else:
                    bad("¡la org objetivo parece PRODUCCIÓN (IsSandbox=false)! El harness solo trabaja contra "
                        "scratch orgs o sandboxes. Cambia org.targetOrgAlias.")
            except (ValueError, KeyError, IndexError):
                note("no pude comprobar IsSandbox; verifícalo a mano")
    out("==============")
    out("doctor: FALLOS - corrige antes de operar." if failed else "doctor: OK.")
    return 1 if failed else 0


def integrity_problems() -> List[str]:
    base = core.root()
    problems: List[str] = []
    try:
        roles = core.load_roles()
        pipeline = core.load_pipeline()
    except (HarnessError, FileNotFoundError) as exc:
        return [f"configuración del harness ilegible: {exc}"]
    role_names = set(roles["roles"])
    agent_dir = base / ".claude" / "agents"
    agent_names = {p.stem for p in agent_dir.glob("*.md")} if agent_dir.exists() else set()
    for name in sorted(role_names - agent_names):
        problems.append(f"rol '{name}' sin .claude/agents/{name}.md")
    for name in sorted(agent_names - role_names):
        problems.append(f"agente '{name}' sin entrada en harness/roles.json")
    skills_dir = base / ".claude" / "skills"
    for path in sorted(agent_dir.glob("*.md")) if agent_dir.exists() else []:
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            problems.append(f"{path.name}: sin frontmatter")
            continue
        front = m.group(1)
        nm = re.search(r"^name:\s*(\S+)", front, re.M)
        if not nm or nm.group(1) != path.stem:
            problems.append(f"{path.name}: 'name' no coincide con el fichero")
        if not re.search(r"^description:\s*\S", front, re.M):
            problems.append(f"{path.name}: sin description")
        sk = re.search(r"^skills:\n((?:\s+-\s+\S+\n?)+)", front, re.M)
        if sk:
            for skill in re.findall(r"-\s+(\S+)", sk.group(1)):
                if not (skills_dir / skill / "SKILL.md").exists():
                    problems.append(f"{path.name}: skill '{skill}' no existe")
    gates_dir = base / "harness" / "gates"
    for section, order in pipeline["order"].items():
        used = {u for rule in pipeline.get(section, []) for u in rule["use"]}
        for name in sorted(used - set(order)):
            problems.append(f"pipeline.{section}: '{name}' no está en order")
        for name in order:
            if section in ("gates", "release_gates"):
                script = gates_dir / f"{name}.sh"
                if not script.exists():
                    problems.append(f"gate '{name}' sin harness/gates/{name}.sh")
            elif name not in role_names:
                problems.append(f"pipeline.{section}: rol desconocido '{name}'")
    settings = base / ".claude" / "settings.json"
    if settings.exists():
        try:
            data = core.read_json(settings)
            for groups in data.get("hooks", {}).values():
                for group in groups:
                    for hook in group.get("hooks", []):
                        for ref in re.findall(r"\.claude/hooks/[\w.-]+", hook.get("command", "")):
                            if not (base / ref).exists():
                                problems.append(f"settings.json referencia {ref}, que no existe")
                        for scr in re.findall(r"hooks/run\"?\s+([\w.-]+)", hook.get("command", "")):
                            if not (base / ".claude" / "hooks" / scr).exists():
                                problems.append(f"settings.json lanza .claude/hooks/{scr}, que no existe")
        except HarnessError as exc:
            problems.append(str(exc))
    else:
        problems.append("falta .claude/settings.json")
    return problems


def cmd_check(args: argparse.Namespace) -> int:
    problems = integrity_problems()
    if problems:
        out(f"{KO} El harness no es coherente:")
        for p in problems:
            out(f"   - {p}")
        return 1
    roles = core.load_roles()
    out(f"{OK} Harness coherente: {len(roles['roles'])} roles, "
        f"{len(gate_names())} gates.")
    return 0


def cmd_org(args: argparse.Namespace) -> int:
    cfg = core.load_config()
    org = cfg["org"]
    target = org["targetOrgAlias"]
    if args.action == "setup":
        rc, _ = _run(["sf", "org", "display", "--target-org", target, "--json"])
        if rc == 0:
            out(f"{OK} '{target}' ya existe y es accesible.")
            return 0
        if org["model"] != "scratch":
            out(f"{KO} '{target}' no está autenticada. Hazlo tú (los agentes no gestionan credenciales):\n"
                f"   sf org login web --alias {target} --instance-url https://test.salesforce.com")
            return 1
        cmd = ["sf", "org", "create", "scratch", "--definition-file", org["scratchDefFile"],
               "--alias", target, "--target-dev-hub", org["devHubAlias"],
               "--duration-days", str(org["scratchDurationDays"]), "--wait", "15"]
        out("$ " + " ".join(cmd))
        return subprocess.call(cmd, cwd=str(core.root()))
    raise HarnessError("acción desconocida")


def cmd_tree_hash(args: argparse.Namespace) -> int:
    out(core.tree_hash(core.load_config()))
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hx", description="CLI del harness Salesforce")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="estado y siguiente paso")
    p.add_argument("--json", action="store_true")
    p.add_argument("--brief", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("propose", help="registrar un borrador de feature")
    p.add_argument("draft")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("approve", help="[HUMANO] aprobar feature o diseño")
    p.add_argument("id")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("start", help="abrir una feature aprobada")
    p.add_argument("id")
    p.add_argument("--no-branch", action="store_true")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("scope", help="fijar o ampliar el scope")
    p.add_argument("id")
    p.add_argument("action", choices=["set", "add"])
    p.add_argument("globs", nargs="+")
    p.add_argument("--reason")
    p.add_argument("--allow-unclassified", action="store_true")
    p.set_defaults(fn=cmd_scope)

    p = sub.add_parser("plan", help="roles, gates y reviews exigidos")
    p.add_argument("id", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("advance", help="pasar a la fase siguiente")
    p.add_argument("id", nargs="?")
    p.set_defaults(fn=cmd_advance)

    p = sub.add_parser("rework", help="devolver a build tras un rechazo")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_rework)

    p = sub.add_parser("block", help="bloquear una feature")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_block)

    p = sub.add_parser("unblock", help="desbloquear")
    p.add_argument("id")
    p.add_argument("--reset-rework", action="store_true")
    p.set_defaults(fn=cmd_unblock)

    p = sub.add_parser("gate", help="ejecutar gates con evidencia")
    p.add_argument("action", choices=["run", "list"])
    p.add_argument("name", nargs="?", default="all")
    p.add_argument("--adhoc", action="store_true", help="sin feature activa (no cuenta como evidencia)")
    p.set_defaults(fn=cmd_gate)

    p = sub.add_parser("verdict", help="registrar el veredicto de una review")
    p.add_argument("role")
    p.add_argument("result", choices=["pass", "fail"])
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_verdict)

    p = sub.add_parser("close", help="[HUMANO] cerrar la feature")
    p.add_argument("id")
    p.set_defaults(fn=cmd_close)

    p = sub.add_parser("metrics", help="métricas por feature")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_metrics)

    p = sub.add_parser("doctor", help="verificar entorno, config y org")
    p.add_argument("--offline", action="store_true", help="no consultar orgs")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("check", help="coherencia interna del harness")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("org", help="preparar la org de desarrollo")
    p.add_argument("action", choices=["setup"])
    p.set_defaults(fn=cmd_org)

    p = sub.add_parser("tree-hash", help="hash del árbol de fuente")
    p.set_defaults(fn=cmd_tree_hash)
    return ap


def _force_utf8() -> None:
    """En Windows la consola suele ser cp1252 y `≥`, `→`, `✓`… tumban el print. Salida siempre UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except HarnessError as exc:
        print(f"{KO} {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"{KO} Falta un fichero del harness: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
