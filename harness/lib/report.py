"""Informe de evidencia de una feature: lo que el cliente o QA firma.

Se construye solo con lo que el harness ya guarda (feature_list.json, .harness/evidence, events.jsonl,
progress/ y docs/specs/). No interpreta ni resume con IA: si un dato no existe, lo dice.
"""
from __future__ import annotations

import base64
import html
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import core

PHASES = [("design", "Diseño"), ("build", "Desarrollo"), ("verify", "Calidad"), ("release", "Entrega")]
GATE_NAME = {"format": "Formato", "secrets": "Secretos", "static": "Análisis estático", "apex-tests": "Tests Apex",
             "lwc-tests": "Tests LWC", "agent-validate": "Validación del agente",
             "deploy-validate": "Validación de despliegue", "regression": "Regresión"}
STATUS = {"pass": ("Correcto", "ok"), "fail": ("Falla", "ko"), "error": ("Entorno", "warn"),
          "stale": ("Caducada", "warn"), "missing": ("Sin evidencia", "warn")}
STATE_ES = {"draft": "Borrador", "approved": "Aprobada", "design": "Diseño", "build": "Desarrollo",
            "verify": "Calidad", "release": "Entrega", "done": "Cerrada", "blocked": "Bloqueada"}


def e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _ts(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def when(s: Optional[str]) -> str:
    t = _ts(s)
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(t)) if t else "—"


def dur(sec: Optional[float]) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 90:
        return f"{sec} s"
    if sec < 5400:
        return f"{round(sec / 60)} min"
    return f"{sec / 3600:.1f} h".replace(".", ",")


def _logo(base: Path) -> str:
    for ext, mime in ((".svg", "image/svg+xml"), (".png", "image/png"), (".webp", "image/webp")):
        p = base / ".harness" / "brand" / f"logo{ext}"
        if p.is_file() and p.stat().st_size < 2 * 1024 * 1024:
            return f'<div class="logo"><img alt="" src="data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"></div>'
    return ""


def _first_section(path: Path, max_lines: int = 18) -> str:
    if not path.is_file():
        return ""
    lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    out: List[str] = []
    for ln in lines:
        if ln.startswith("#") and out and any(x.strip() for x in out):
            if ln.startswith("# "):
                continue
            if len(out) > 3:
                break
        out.append(ln)
        if len(out) >= max_lines:
            break
    return "\n".join(out).strip()


def _summary_of(path: Path) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^#{1,6}\s*(?:Resumen|Veredicto)\s*$\n+(.+?)(?:\n#|\Z)", text, re.M | re.S | re.I)
    if not m:
        return ""
    first = next((ln for ln in m.group(1).splitlines() if ln.strip()), "")
    return re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+|[*_`]", "", first).strip()[:240]


def build(fid: str, plan_for: Callable, metrics_row: Callable[[Dict[str, Any], List[Dict[str, Any]]], Dict[str, Any]]) -> str:
    base = core.root()
    cfg = core.load_config()
    feat = core.find_feature(core.load_features(), fid)
    events = core.read_events()
    evs = [x for x in events if x.get("feature") == fid]
    try:
        m = metrics_row(feat, events)
    except Exception:  # noqa: BLE001 - una feature antigua sin historia completa no impide el informe
        m = {"phase_time_s": {}, "lead_time_s": None, "first_pass_gates": None, "rework_loops": feat.get("rework_count", 0)}
    m.setdefault("phase_time_s", {})
    try:
        tree = core.tree_hash(cfg)
    except Exception:  # noqa: BLE001
        tree = "desconocido"
    try:
        plan, _ = plan_for(feat, cfg)
    except Exception:  # noqa: BLE001 - el informe sale aunque el plan no se pueda derivar
        plan = {}
    gates = list(plan.get("gates", [])) + list(plan.get("release_gates", []))
    reviews = list(plan.get("reviews", []))
    for p in sorted(core.evidence_dir(fid).glob("gate-*.json")) if core.evidence_dir(fid).exists() else []:
        if p.stem[5:] not in gates:
            gates.append(p.stem[5:])
    for p in sorted(core.evidence_dir(fid).glob("review-*.json")) if core.evidence_dir(fid).exists() else []:
        if p.stem[7:] not in reviews:
            reviews.append(p.stem[7:])

    # --- comprobaciones automáticas ---
    gate_rows, gate_ok = [], 0
    for g in gates:
        ev = core.read_evidence(fid, f"gate-{g}") or {}
        st, _ = core.evidence_status(fid, f"gate-{g}", tree)
        gate_ok += st == "pass"
        lab, cls = STATUS.get(st, (st, ""))
        runs = sum(1 for x in evs if x["event"] == "gate" and x.get("gate") == g)
        gate_rows.append(f"<tr><td>{e(GATE_NAME.get(g, g))}</td><td><span class='pill {cls}'>{e(lab)}</span></td>"
                         f"<td>{dur(ev.get('duration_s'))}</td><td>{runs or '—'}</td><td class='mono'>{e(ev.get('tree_hash', '—'))}</td>"
                         f"<td>{when(ev.get('finished_at'))}</td><td>{e(ev.get('summary', ''))[:300]}</td></tr>")
    # --- revisiones ---
    rev_rows, rev_ok = [], 0
    for r in reviews:
        ev = core.read_evidence(fid, f"review-{r}") or {}
        st, _ = core.evidence_status(fid, f"review-{r}", tree)
        rev_ok += st == "pass"
        lab, cls = STATUS.get(st, (st, ""))
        rep = core.report_path(fid, r)
        rev_rows.append(f"<tr><td>{e(r)}</td><td><span class='pill {cls}'>{e(lab)}</span></td>"
                        f"<td>{e(ev.get('blockers', '—'))}</td><td>{e(ev.get('summary') or _summary_of(rep))}</td>"
                        f"<td class='mono'>{e(rep.relative_to(base).as_posix()) if rep.exists() else '—'}</td></tr>")
    # --- trabajo de cada agente ---
    work_rows = []
    stops = [x for x in evs if x["event"] == "subagent_stop"]
    for x in stops:
        work_rows.append(f"<tr><td>{e(x.get('role'))}</td><td>{dur(x.get('duration_s'))}</td>"
                         f"<td>{e(x.get('summary') or _summary_of(core.report_path(fid, x.get('role', ''))))}</td>"
                         f"<td class='mono'>{e(x.get('report', ''))}</td></tr>")
    # --- cambios ---
    try:
        changed = core.changed_files(feat)
    except Exception:  # noqa: BLE001
        changed = []
    product = [f for f in changed if core.in_package(f, cfg)]
    docs = [f for f in changed if not core.in_package(f, cfg) and f.startswith(("docs/", "manifest/"))]
    changed_rows = "".join(f"<tr><td class='mono'>{e(f)}</td><td>{e(core.classify(f))}</td></tr>" for f in product)
    changed_rows += "".join(f"<tr><td class='mono'>{e(f)}</td><td>documentación</td></tr>" for f in docs)
    # --- aprobaciones humanas ---
    approvals = [("Feature aprobada", feat.get("approved_at")), ("Diseño aprobado", feat.get("design_approved_at")),
                 ("Feature cerrada", feat.get("closed_at"))]
    ui = {x.get("action"): x for x in evs if x["event"] == "human_action" and x.get("rc") == 0}
    appr_rows = "".join(
        f"<tr><td>{e(lbl)}</td><td>{when(at)}</td><td>{'centro de control' if (k in ui) else ('terminal' if at else '—')}</td></tr>"
        for (lbl, at), k in zip(approvals, ("approve", "approve", "close")) if at or lbl != "Diseño aprobado")
    # --- cronología ---
    hist = feat.get("history", [])
    hist = [h for h in hist if isinstance(h, dict)]
    hist_rows = "".join(f"<tr><td>{when(h.get('at'))}</td><td>{e(STATE_ES.get(h.get('from') or '', h.get('from') or '—'))} → "
                        f"{e(STATE_ES.get(h.get('to'), h.get('to')))}</td><td>{e(h.get('note', ''))}</td></tr>" for h in hist)
    # --- seguridad ---
    blocks = [x for x in evs if x["event"] == "guard_block"]
    block_rows = "".join(f"<tr><td>{when(x.get('at'))}</td><td>{e(x.get('role') or 'orchestrator')}</td><td>{e(x.get('rule'))}</td>"
                         f"<td>{e((x.get('detail') or '')[:200])}</td></tr>" for x in blocks)
    # --- requisitos y diseño ---
    def _ac(i: int, a: Any) -> str:
        if isinstance(a, dict):
            return f"<li><b>{e(a.get('id') or f'AC-{i + 1}')}</b> {e(a.get('text') or a.get('description') or '')}</li>"
        return f"<li><b>AC-{i + 1}</b> {e(a)}</li>"
    acs = "".join(_ac(i, a) for i, a in enumerate(feat.get("acceptance_criteria") or []))
    oos = "".join(f"<li>{e(x.get('text') if isinstance(x, dict) else x)}</li>" for x in feat.get("out_of_scope") or [])
    design_path = core.spec_dir(fid) / "design.md"
    design = _first_section(design_path)
    phase_cells = "".join(f"<div class='kpi'><b>{dur(m['phase_time_s'].get(k))}</b><span>{lbl}</span></div>"
                          for k, lbl in PHASES)
    verdict_ok = feat["status"] == "done" and gate_ok == len(gates) and rev_ok == len(reviews)
    headline = ("Cerrada con todas las comprobaciones y revisiones en verde para el código entregado."
                if verdict_ok else
                f"Estado: {STATE_ES.get(feat['status'], feat['status'])}. {gate_ok}/{len(gates)} comprobaciones y "
                f"{rev_ok}/{len(reviews)} revisiones en verde para el código actual.")
    fp = f"{m['first_pass_gates']:.0f} %".replace(".", ",") if m.get("first_pass_gates") is not None else "—"
    generated = time.strftime("%d/%m/%Y %H:%M")
    org = cfg["org"]
    empty = lambda cols, msg: f"<tr><td colspan='{cols}' class='muted'>{msg}</td></tr>"  # noqa: E731

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>Evidencia {e(fid)} · {e(feat['title'])}</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--ink:#3c3c3a;--muted:#77756f;--line:#e4e2de;--soft:#f7f6f4;--poppy:#f8485e;--ok:#5ab891;--warn:#fcc354}}
*{{box-sizing:border-box}} body{{margin:0;background:#efeeee;color:var(--ink);font:400 12.5px/1.55 Montserrat,system-ui,sans-serif}}
.page{{max-width:980px;margin:24px auto;background:#fff;border-radius:15px;padding:36px 44px;box-shadow:0 8px 24px -12px rgba(60,60,58,.25)}}
header{{display:flex;gap:18px;align-items:center;border-bottom:3px solid var(--poppy);padding-bottom:18px;margin-bottom:22px}}
.logo{{background:var(--poppy);border-radius:12px;padding:10px 14px}} .logo img{{height:22px;display:block}}
h1{{font:300 24px/1.2 Montserrat;margin:4px 0 0}} h1 b{{font-weight:600}}
.eyebrow{{font:700 10.5px Montserrat;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}}
h2{{font:600 15px Montserrat;margin:28px 0 10px;padding-top:6px;border-top:1px solid var(--line)}}
.verdict{{padding:14px 18px;border-radius:12px;background:var(--soft);border-left:4px solid {'var(--ok)' if verdict_ok else 'var(--warn)'};font-size:14px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}}
.kpi{{background:var(--soft);border-radius:12px;padding:10px 12px}} .kpi b{{display:block;font:600 18px Montserrat}} .kpi span{{font-size:11px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:12px}} th{{text-align:left;font:700 10px Montserrat;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--line);padding:6px 8px}}
td{{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}}
.pill{{display:inline-block;padding:2px 9px;border-radius:12px;font:600 11px Montserrat;background:var(--soft);white-space:nowrap}}
.pill.ok{{background:#e3f3ec;color:#2f7d5b}} .pill.ko{{background:#fddade;color:#b5293d}} .pill.warn{{background:#fdf1d6;color:#8a6110}}
.mono{{font:11px ui-monospace,Consolas,monospace;word-break:break-all}} .muted{{color:var(--muted)}}
pre{{background:var(--soft);border-radius:12px;padding:12px 14px;white-space:pre-wrap;font:11.5px/1.5 ui-monospace,Consolas,monospace;margin:0}}
ul{{margin:6px 0;padding-left:20px}} li{{margin:3px 0}}
footer{{margin-top:28px;padding-top:12px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}}
.print{{position:fixed;right:20px;top:20px;background:var(--poppy);color:#fff;border:0;border-radius:12px;padding:9px 16px;font:600 13px Montserrat;cursor:pointer}}
@media print{{body{{background:#fff}} .page{{box-shadow:none;margin:0;max-width:none;padding:0}} .print{{display:none}} h2{{break-after:avoid}} tr{{break-inside:avoid}}}}
</style></head><body>
<button class="print" onclick="print()">Guardar como PDF</button>
<div class="page">
<header>{_logo(base)}<div><div class="eyebrow">Informe de evidencia · {e(cfg.get('project'))}</div>
<h1><b>{e(fid)}</b> · {e(feat['title'])}</h1>
<div class="muted">Tamaño {e(feat.get('size'))} · {e(feat.get('type', ''))} · org de desarrollo <b>{e(org.get('targetOrgAlias'))}</b> · rama {e(feat.get('branch') or '—')}</div></div></header>

<div class="verdict">{e(headline)}</div>
<div class="kpis"><div class="kpi"><b>{dur(m.get('lead_time_s'))}</b><span>De inicio a cierre</span></div>
<div class="kpi"><b>{fp}</b><span>Comprobaciones bien a la primera</span></div>
<div class="kpi"><b>{m.get('rework_loops', 0)}</b><span>Correcciones (rework)</span></div>
<div class="kpi"><b>{len(blocks)}</b><span>Acciones impedidas por las guardas</span></div></div>
<div class="kpis">{phase_cells}</div>

<h2>Qué se pidió</h2>
<p>{e(feat.get('description') or 'Sin descripción.')}</p>
<div class="eyebrow">Criterios de aceptación</div><ul>{acs or '<li class="muted">Sin criterios registrados.</li>'}</ul>
{f'<div class="eyebrow">Fuera de alcance</div><ul>{oos}</ul>' if oos else ''}

<h2>Diseño</h2>
{f'<pre>{e(design)}</pre><p class="muted mono">{e(design_path.relative_to(base).as_posix())}</p>' if design else '<p class="muted">No hay documento de diseño en docs/specs/' + e(fid) + '/design.md.</p>'}

<h2>Aprobaciones humanas</h2>
<table><tr><th>Decisión</th><th>Cuándo</th><th>Desde</th></tr>{appr_rows or empty(3, 'Sin aprobaciones registradas.')}</table>

<h2>Qué se cambió</h2>
<table><tr><th>Fichero</th><th>Tipo</th></tr>{changed_rows or empty(2, 'Sin cambios detectados respecto a la rama base.')}</table>

<h2>Comprobaciones automáticas</h2>
<p class="muted">Cada resultado está atado al hash del código comprobado. Hash del código actual: <span class="mono">{e(tree)}</span>. Si no coincide, la evidencia está caducada.</p>
<table><tr><th>Gate</th><th>Resultado</th><th>Duración</th><th>Ejecuciones</th><th>Hash</th><th>Cuándo</th><th>Detalle</th></tr>{''.join(gate_rows) or empty(7, 'Sin gates en el plan.')}</table>

<h2>Revisiones</h2>
<table><tr><th>Revisor</th><th>Veredicto</th><th>Bloqueantes</th><th>Resumen</th><th>Informe</th></tr>{''.join(rev_rows) or empty(5, 'Sin revisiones en el plan.')}</table>

<h2>Trabajo de cada agente</h2>
<table><tr><th>Agente</th><th>Duración</th><th>Resumen de su informe</th><th>Informe</th></tr>{''.join(work_rows) or empty(4, 'Sin trabajo registrado.')}</table>

<h2>Acciones impedidas por las guardas</h2>
<table><tr><th>Cuándo</th><th>Agente</th><th>Regla</th><th>Detalle</th></tr>{block_rows or empty(4, 'Ninguna: ningún agente intentó saltarse las reglas.')}</table>

<h2>Cronología</h2>
<table><tr><th>Cuándo</th><th>Cambio de fase</th><th>Nota</th></tr>{hist_rows or empty(3, 'Sin historia.')}</table>

<footer>Generado el {generated} por el harness a partir de feature_list.json, .harness/evidence, events.jsonl y los informes de progress/.
Los resúmenes de trabajo y de revisión salen de los informes que escribieron los agentes; todo lo demás (fases, aprobaciones, resultados, hashes, bloqueos) son registros del propio proceso, sin interpretar.</footer>
</div></body></html>"""


def error_page(fid: str, exc: BaseException) -> str:
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Informe {e(fid)}</title>
<style>body{{font:14px/1.6 system-ui,sans-serif;color:#3c3c3a;background:#efeeee;margin:0}}
.box{{max-width:720px;margin:60px auto;background:#fff;border-radius:15px;padding:28px 32px;border-left:4px solid #f8485e}}
code{{background:#f7f6f4;padding:2px 6px;border-radius:6px}}</style></head><body><div class="box">
<h2>No he podido generar el informe de {e(fid)}</h2><p>El motivo:</p><p><code>{e(type(exc).__name__)}: {e(exc)}</code></p>
<p>Prueba <code>./hx report {e(fid)}</code> en la terminal para ver el detalle completo y pásame el mensaje.</p></div></body></html>"""
