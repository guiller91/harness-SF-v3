"""Configuración editable desde el centro de control (./hx watch).

Qué se puede tocar desde la interfaz y qué no:
  - Entornos (org de desarrollo, de validación, DevHub, alias protegidos) y login web en Salesforce.
  - Políticas con parámetros: cobertura, nivel de tests, severidad del análisis, reworks, aprobación de
    diseño. Son números y listas cerradas; el código de los gates no se edita aquí.
  - Agentes: descripción, modelo, skills e instrucciones. El nombre no (lo usa roles.json).
  - Las guardas (hooks) NO: son la frontera de seguridad y solo cambian por git y revisión.

Cada cambio deja una copia del fichero anterior en .harness/config-history/, pasa `./hx check` y, si el
harness deja de ser coherente, se deshace solo. Queda en events.jsonl como `config_change`.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import core

ALIAS = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
MODELS = ("sonnet", "opus", "haiku", "inherit")
TEST_LEVELS = ("RunSpecifiedTests", "RunLocalTests", "RunAllTestsInOrg")
SIZES = ("S", "M", "L")
LOGIN_URLS = {"production": "https://login.salesforce.com", "sandbox": "https://test.salesforce.com"}
MYDOMAIN = re.compile(r"^https://[a-z0-9-]+(?:--[a-z0-9-]+)?(?:\.sandbox|\.scratch|\.develop|\.trailblaze)?"
                      r"\.my\.salesforce\.com/?$", re.I)


# --------------------------------------------------------------------------- #
# Utilidades comunes
# --------------------------------------------------------------------------- #

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def history_dir() -> Path:
    return core.root() / ".harness" / "config-history"


def _rel(path: Path) -> str:
    return path.relative_to(core.root()).as_posix()


def diff(old: str, new: str, name: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}", n=2))


def check(cli_path: Path) -> Tuple[bool, str]:
    proc = subprocess.run([sys.executable, str(cli_path), "check"], cwd=core.root(), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def write_checked(path: Path, new_text: str, kind: str, cli_path: Path, note: str = "") -> Tuple[int, str]:
    """Escribe con copia previa, pasa ./hx check y deshace si falla. Devuelve (rc, mensaje)."""
    old = path.read_bytes() if path.exists() else b""
    new = new_text.encode("utf-8")
    if old == new:
        return 0, "Sin cambios."
    hist = history_dir()
    hist.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = hist / f"{stamp}__{_rel(path).replace('/', '__')}"
    backup.write_bytes(old)
    path.write_bytes(new)
    ok, output = check(cli_path)
    if not ok:
        path.write_bytes(old)
        backup.unlink(missing_ok=True)
        return 2, "El harness dejaría de ser coherente; no se ha guardado nada.\n" + output
    core.log_event("config_change", what=kind, file=_rel(path), before=_sha(old), after=_sha(new),
                   backup=backup.name, note=note[:200], source="ui")
    return 0, "Guardado y comprobado con ./hx check."


def history(limit: int = 30) -> List[Dict[str, Any]]:
    out = []
    for e in reversed(core.read_events()):
        if e.get("event") == "config_change":
            out.append({"at": e.get("at"), "kind": e.get("what"), "file": e.get("file"), "backup": e.get("backup"), "note": e.get("note")})
            if len(out) >= limit:
                break
    return out


def undo(backup_name: str, cli_path: Path) -> Tuple[int, str]:
    if not re.match(r"^[\w.-]+$", backup_name or ""):
        return 2, "Copia no válida."
    backup = history_dir() / backup_name
    if not backup.is_file():
        return 2, "Esa copia ya no existe."
    rel = backup_name.split("__", 1)[1].replace("__", "/")
    target = core.root() / rel
    if rel != "harness.config.json" and not re.match(r"^\.claude/agents/[\w-]+\.md$", rel):
        return 2, "Esa copia no es de un fichero editable desde el panel."
    return write_checked(target, backup.read_text(encoding="utf-8"), "undo", cli_path, note=f"deshace {backup_name}")


# --------------------------------------------------------------------------- #
# Entornos y políticas (harness.config.json)
# --------------------------------------------------------------------------- #

def config_path() -> Path:
    return core.root() / "harness.config.json"


def read_raw_config() -> Dict[str, Any]:
    return json.loads(config_path().read_text(encoding="utf-8"))


def view_config() -> Dict[str, Any]:
    cfg = core.load_config()
    org, q, wf = cfg["org"], cfg["quality"], cfg["workflow"]
    return {
        "environments": {"model": org.get("model"), "target": org.get("targetOrgAlias", ""),
                         "validation": org.get("validationOrgAlias") or "", "devhub": org.get("devHubAlias") or "",
                         "protected": list(org.get("protectedAliases", []))},
        "policies": {"coverage": q.get("coverageGatePerClass"), "testLevel": q.get("apexTestLevel"),
                     "severity": q.get("analyzer", {}).get("severityThreshold"),
                     "maxRework": wf.get("maxReworkLoops"), "designApproval": wf.get("designApprovalForSizes", [])},
        "choices": {"models": ["scratch", "sandbox"], "testLevels": list(TEST_LEVELS), "sizes": list(SIZES)},
    }


def _dump(data: Any, ind: int = 0) -> str:
    """JSON con sangría de 2 y las listas de valores simples en una línea, como el fichero original."""
    pad, inner = "  " * ind, "  " * (ind + 1)
    if isinstance(data, dict):
        if not data:
            return "{}"
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {_dump(v, ind + 1)}" for k, v in data.items()]
        text = "{\n" + ",\n".join(items) + f"\n{pad}}}"
    elif isinstance(data, list):
        if all(not isinstance(x, (dict, list)) for x in data):
            text = "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in data) + "]"
        else:
            text = "[\n" + ",\n".join(inner + _dump(x, ind + 1) for x in data) + f"\n{pad}]"
    else:
        text = json.dumps(data, ensure_ascii=False)
    return text + ("\n" if ind == 0 else "")


def plan_environments(body: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Devuelve (texto_nuevo, error)."""
    model = body.get("model")
    target = str(body.get("target") or "").strip()
    validation = str(body.get("validation") or "").strip()
    devhub = str(body.get("devhub") or "").strip()
    protected = [str(x).strip() for x in body.get("protected") or [] if str(x).strip()]
    if model not in ("scratch", "sandbox"):
        return None, "Modelo de org no válido (scratch o sandbox)."
    for name, value in (("desarrollo", target), ("validación", validation), ("DevHub", devhub)):
        if value and not ALIAS.match(value):
            return None, f"Alias de {name} no válido: solo letras, números, punto, guion y guion bajo."
    if not target:
        return None, "Falta la org de desarrollo."
    if any(not ALIAS.match(p) for p in protected):
        return None, "Hay un alias protegido no válido."
    low = {p.lower() for p in protected}
    for name, value in (("desarrollo", target), ("validación", validation)):
        if value and value.lower() in low:
            return None, f"La org de {name} ('{value}') está entre las protegidas: los agentes no podrían usarla."
    if model == "scratch" and not devhub:
        return None, "Con scratch orgs hace falta el alias del DevHub."
    raw = read_raw_config()
    org = raw.setdefault("org", {})
    org.update({"model": model, "targetOrgAlias": target, "validationOrgAlias": validation,
                "devHubAlias": devhub, "protectedAliases": protected})
    return _dump(raw), ""


def plan_policies(body: Dict[str, Any]) -> Tuple[Optional[str], str]:
    try:
        coverage = int(body.get("coverage"))
        severity = int(body.get("severity"))
        max_rework = int(body.get("maxRework"))
    except (TypeError, ValueError):
        return None, "Cobertura, severidad y reworks deben ser números."
    level = body.get("testLevel")
    sizes = [s for s in body.get("designApproval") or [] if s in SIZES]
    if not 75 <= coverage <= 100:
        return None, "La cobertura por clase va de 75 a 100 (Salesforce exige al menos 75 % para desplegar)."
    if not 1 <= severity <= 5:
        return None, "La severidad del análisis va de 1 (solo críticas) a 5 (todas)."
    if not 1 <= max_rework <= 10:
        return None, "Los ciclos de rework van de 1 a 10."
    if level not in TEST_LEVELS:
        return None, "Nivel de tests no válido."
    raw = read_raw_config()
    q = raw.setdefault("quality", {})
    q["coverageGatePerClass"] = coverage
    q["apexTestLevel"] = level
    q.setdefault("analyzer", {})["severityThreshold"] = severity
    wf = raw.setdefault("workflow", {})
    wf["maxReworkLoops"] = max_rework
    wf["designApprovalForSizes"] = [s for s in SIZES if s in sizes]
    return _dump(raw), ""


# --------------------------------------------------------------------------- #
# Agentes (.claude/agents/<rol>.md)
# --------------------------------------------------------------------------- #

FRONT = re.compile(r"^---\n(.*?)\n---\n?", re.S)


def agents_dir() -> Path:
    return core.root() / ".claude" / "agents"


def available_skills() -> List[str]:
    d = core.root() / ".claude" / "skills"
    return sorted(p.parent.name for p in d.glob("*/SKILL.md")) if d.exists() else []


def parse_agent(text: str) -> Dict[str, Any]:
    m = FRONT.match(text)
    front, body = (m.group(1), text[m.end():]) if m else ("", text)
    get = lambda k: (re.search(rf"^{k}:\s*(.*)$", front, re.M) or [None, ""])[1].strip()  # noqa: E731
    sk = re.search(r"^skills:\n((?:[ \t]+-[ \t]+\S+\n?)+)", front + "\n", re.M)
    desc = get("description")
    if desc.startswith('"') and desc.endswith('"'):
        try:
            desc = json.loads(desc)
        except ValueError:
            pass
    return {"name": get("name"), "description": desc, "model": get("model") or "inherit",
            "skills": re.findall(r"-\s+(\S+)", sk.group(1)) if sk else [], "body": body, "front": front}


def list_agents() -> List[Dict[str, Any]]:
    roles = core.load_roles()["roles"]
    out = []
    for path in sorted(agents_dir().glob("*.md")):
        a = parse_agent(path.read_text(encoding="utf-8"))
        spec = roles.get(path.stem, {})
        out.append({"name": path.stem, "description": a["description"], "model": a["model"], "skills": a["skills"],
                    "class": spec.get("class", "orchestrator" if path.stem == "orchestrator" else ""),
                    "body": a["body"]})
    return out


def _agent_path(name: str) -> Optional[Path]:
    if not re.match(r"^[a-z][a-z0-9-]{1,40}$", name or ""):
        return None
    path = agents_dir() / f"{name}.md"
    return path if path.is_file() else None


def plan_agent(body: Dict[str, Any]) -> Tuple[Optional[Path], Optional[str], str]:
    path = _agent_path(str(body.get("name") or ""))
    if not path:
        return None, None, "Agente desconocido."
    text = path.read_text(encoding="utf-8")
    m = FRONT.match(text)
    if not m:
        return None, None, "El agente no tiene frontmatter."
    front = m.group(1)
    desc = " ".join(str(body.get("description") or "").split())
    if not 10 <= len(desc) <= 400:
        return None, None, "La descripción debe tener entre 10 y 400 caracteres: es lo que usa el orquestador para elegir."
    if re.search(r":\s|\s#|^[\[{>|*&!%@`'\"]", desc):
        desc = json.dumps(desc, ensure_ascii=False)  # YAML: si puede confundirse, entre comillas
    model = body.get("model")
    if model not in MODELS:
        return None, None, "Modelo no válido."
    skills = [s for s in body.get("skills") or [] if s in available_skills()]
    instructions = str(body.get("body") or "")
    if len(instructions.strip()) < 40:
        return None, None, "Las instrucciones están casi vacías: el agente no sabría qué hacer."
    if len(instructions) > 60000:
        return None, None, "Instrucciones demasiado largas."
    front = re.sub(r"^description:.*$", lambda _: f"description: {desc}", front, count=1, flags=re.M)
    if re.search(r"^model:", front, re.M):
        front = re.sub(r"^model:.*$", lambda _: f"model: {model}", front, count=1, flags=re.M)
    else:
        front += f"\nmodel: {model}"
    block = "skills:\n" + "".join(f"  - {s}\n" for s in skills) if skills else ""
    if re.search(r"^skills:\n(?:[ \t]+-[ \t]+\S+\n?)*", front + "\n", re.M):
        front = re.sub(r"^skills:\n(?:[ \t]+-[ \t]+\S+\n?)*", block, front + "\n", count=1, flags=re.M).rstrip("\n")
    elif block:
        front += "\n" + block.rstrip("\n")
    instructions = instructions.replace("\r\n", "\n")
    return path, f"---\n{front}\n---\n{instructions if instructions.startswith(chr(10)) else chr(10) + instructions}", ""


# --------------------------------------------------------------------------- #
# Orgs de Salesforce (la CLI guarda las credenciales; el harness nunca las ve)
# --------------------------------------------------------------------------- #

def _sf() -> Optional[str]:
    return shutil.which("sf")


def _kind(org: Dict[str, Any]) -> str:
    url = str(org.get("instanceUrl") or "").lower()
    if org.get("isScratch") or ".scratch." in url:
        return "scratch"
    if org.get("isSandbox") or ".sandbox." in url or "--" in url.split("//")[-1].split(".")[0]:
        return "sandbox"
    if org.get("isDevHub"):
        return "devhub"
    return "production"


def list_orgs() -> Dict[str, Any]:
    sf = _sf()
    if not sf:
        return {"available": False, "orgs": [], "error": "No encuentro la CLI `sf` en esta máquina."}
    try:
        proc = subprocess.run([sf, "org", "list", "--json"], cwd=core.root(), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=90)
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"available": True, "orgs": [], "error": f"`sf org list` no respondió: {exc}"}
    seen: Dict[str, Dict[str, Any]] = {}
    for group in (data.get("result") or {}).values():
        if not isinstance(group, list):
            continue
        for o in group:
            user = o.get("username")
            if not user or user in seen:
                continue
            seen[user] = {"alias": o.get("alias") or "", "username": user, "instanceUrl": o.get("instanceUrl") or "",
                          "kind": _kind(o), "status": o.get("connectedStatus") or o.get("status") or "",
                          "expires": o.get("expirationDate") or ""}
    return {"available": True, "orgs": sorted(seen.values(), key=lambda x: (x["alias"] == "", x["alias"].lower())),
            "error": ""}


class LoginJobs:
    """`sf org login web` abre el navegador del humano; aquí solo se espera a que termine."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: Dict[str, Dict[str, Any]] = {}

    def start(self, body: Dict[str, Any]) -> Tuple[int, str, Optional[str]]:
        sf = _sf()
        if not sf:
            return 3, "No encuentro la CLI `sf` en esta máquina.", None
        alias = str(body.get("alias") or "").strip()
        kind = body.get("kind")
        if not ALIAS.match(alias):
            return 2, "Alias no válido: solo letras, números, punto, guion y guion bajo.", None
        if kind in LOGIN_URLS:
            url = LOGIN_URLS[kind]
        elif kind == "mydomain":
            url = str(body.get("url") or "").strip()
            if not MYDOMAIN.match(url):
                return 2, "La URL debe ser tu My Domain de Salesforce: https://<empresa>.my.salesforce.com", None
        else:
            return 2, "Tipo de org no válido.", None
        with self.lock:
            if any(j["state"] == "running" for j in self.jobs.values()):
                return 2, "Ya hay un login en marcha: termínalo en el navegador.", None
            job = f"L{len(self.jobs) + 1}"
            self.jobs[job] = {"state": "running", "alias": alias, "kind": kind, "output": ""}
        argv = [sf, "org", "login", "web", "--alias", alias, "--instance-url", url, "--json"]
        threading.Thread(target=self._run, args=(job, argv, kind == "production", alias), daemon=True).start()
        return 0, "Se ha abierto el navegador: inicia sesión allí.", job

    def _run(self, job: str, argv: List[str], production: bool, alias: str) -> None:
        try:
            proc = subprocess.run(argv, cwd=core.root(), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=600)
            ok = proc.returncode == 0
            msg = ""
            try:
                data = json.loads(proc.stdout or "{}")
                msg = data.get("message") or (data.get("result") or {}).get("username", "")
            except ValueError:
                msg = (proc.stdout + proc.stderr).strip()[-400:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok, msg = False, str(exc)
        note = ""
        if ok and production:
            try:
                note = protect_alias(alias)
            except Exception as exc:  # noqa: BLE001 - el login ya está hecho; avisamos
                note = f" · OJO: no pude protegerla automáticamente ({exc}); añádela a protegidos."
        core.log_event("org_login", alias=alias, ok=ok, production=production, source="ui")
        with self.lock:
            self.jobs[job].update({"state": "done" if ok else "failed", "output": (msg + note).strip()})

    def view(self, job: str) -> Dict[str, Any]:
        with self.lock:
            return dict(self.jobs.get(job) or {"state": "unknown"})


def protect_alias(alias: str) -> str:
    """Una org de producción entra directamente en protectedAliases: ningún agente podrá usarla."""
    raw = read_raw_config()
    prot = raw.setdefault("org", {}).setdefault("protectedAliases", [])
    if alias.lower() in {p.lower() for p in prot}:
        return ""
    prot.append(alias)
    path = config_path()
    old = path.read_bytes()
    path.write_text(_dump(raw), encoding="utf-8")
    core.log_event("config_change", what="protect", file="harness.config.json", before=_sha(old),
                   after=_sha(path.read_bytes()), note=f"producción '{alias}' protegida al conectar", source="ui")
    return f" · '{alias}' es producción: añadida a los alias protegidos."
