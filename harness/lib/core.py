"""Núcleo del harness: configuración, estado de features, hashing del árbol de
fuente, clasificación de metadata, pipeline derivado y evidencia.

Solo librería estándar (Python >= 3.8). Lo usan la CLI (`./hx`) y los hooks.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

def root() -> Path:
    """Raíz del proyecto. Los hooks reciben CLAUDE_PROJECT_DIR; la CLI usa su ubicación."""
    env = os.environ.get("HX_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / "harness.config.json").exists():
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


CONFIG_FILE = "harness.config.json"
FEATURES_FILE = "feature_list.json"
STATE_DIR = ".harness"
EVIDENCE_DIR = ".harness/evidence"
RUN_DIR = ".harness/run"
EVENTS_FILE = ".harness/events.jsonl"
PIPELINE_FILE = "harness/pipeline.json"
ROLES_FILE = "harness/roles.json"

# Estados de una feature. El orden de ACTIVE_PHASES es el orden del pipeline.
ACTIVE_PHASES = ["design", "build", "verify", "release"]
ALL_STATUSES = ["draft", "approved"] + ACTIVE_PHASES + ["done", "blocked"]


class HarnessError(Exception):
    """Error de negocio del harness (precondición no cumplida, estado inválido...)."""


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #

def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        if default is not None:
            return default
        raise
    except json.JSONDecodeError as exc:
        raise HarnessError(f"{path} no es JSON válido: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG: Dict[str, Any] = {
    "project": "CHANGE_ME",
    "org": {
        "model": "scratch",
        "devHubAlias": "DevHub",
        "targetOrgAlias": "harness-dev",
        "validationOrgAlias": "",
        "protectedAliases": ["prod", "production", "produccion"],
        "scratchDefFile": "config/project-scratch-def.json",
        "scratchDurationDays": 7,
    },
    "source": {"packageDirs": ["force-app"]},
    "quality": {
        "coverageGatePerClass": 85,
        "apexTestLevel": "RunLocalTests",
        "analyzer": {
            "ruleSelector": ["Recommended"],
            "severityThreshold": 3,
            "configFile": "code-analyzer.yml",
            "scope": "changed",
        },
    },
    "workflow": {"maxReworkLoops": 3, "designApprovalForSizes": ["L"]},
    "git": {"featureBranchPrefix": "feat/", "protectedBranches": ["main", "master"]},
}


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(base: Optional[Path] = None) -> Dict[str, Any]:
    base = base or root()
    user = read_json(base / CONFIG_FILE, default={})
    return _merge(DEFAULT_CONFIG, user)


def package_dirs(cfg: Dict[str, Any]) -> List[str]:
    dirs = cfg.get("source", {}).get("packageDirs") or ["force-app"]
    return [d.strip("/") for d in dirs]


def allowed_orgs(cfg: Dict[str, Any]) -> Dict[str, str]:
    """Alias -> rol ('target' | 'validation' | 'devhub')."""
    org = cfg["org"]
    out: Dict[str, str] = {}
    if org.get("devHubAlias"):
        out[org["devHubAlias"]] = "devhub"
    if org.get("validationOrgAlias"):
        out[org["validationOrgAlias"]] = "validation"
    if org.get("targetOrgAlias"):
        out[org["targetOrgAlias"]] = "target"
    return out


# --------------------------------------------------------------------------- #
# Globs con soporte de ** (estilo gitignore simplificado)
# --------------------------------------------------------------------------- #

_GLOB_CACHE: Dict[str, "re.Pattern[str]"] = {}


def glob_to_regex(pattern: str) -> "re.Pattern[str]":
    if pattern in _GLOB_CACHE:
        return _GLOB_CACHE[pattern]
    pat = pattern.strip().lstrip("./")
    i, out = 0, []
    while i < len(pat):
        ch = pat[i]
        if ch == "*":
            if pat[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    rx = re.compile("^" + "".join(out) + "$")
    _GLOB_CACHE[pattern] = rx
    return rx


def glob_match(path: str, pattern: str) -> bool:
    path = path.replace("\\", "/").lstrip("./")
    pattern = pattern.strip()
    if pattern.endswith("/"):
        pattern += "**"
    return bool(glob_to_regex(pattern).match(path))


def match_any(path: str, patterns: Iterable[str]) -> bool:
    """Coincide con algún patrón positivo y con ninguno negado ('!patrón')."""
    pats = list(patterns)
    neg = [p[1:] for p in pats if p.startswith("!")]
    pos = [p for p in pats if not p.startswith("!")]
    if any(glob_match(path, p) for p in neg):
        return False
    return any(glob_match(path, p) for p in pos)


def rel(path: str, base: Optional[Path] = None) -> Optional[str]:
    """Ruta relativa al proyecto (posix) o None si queda fuera."""
    base = base or root()
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    try:
        out = os.path.relpath(os.path.normpath(str(p)), str(base)).replace("\\", "/")
    except ValueError:
        return None
    return None if out == ".." or out.startswith("../") else out


def expand_pkg(patterns: Iterable[str], cfg: Dict[str, Any]) -> List[str]:
    """Expande el marcador {pkg} a cada packageDir: '{pkg}/**/classes/**'."""
    out: List[str] = []
    for pat in patterns:
        neg = pat.startswith("!")
        body = pat[1:] if neg else pat
        if "{pkg}" in body:
            for d in package_dirs(cfg):
                out.append(("!" if neg else "") + body.replace("{pkg}", d))
        else:
            out.append(pat)
    return out


def in_package(path: str, cfg: Dict[str, Any]) -> bool:
    return any(path == d or path.startswith(d + "/") for d in package_dirs(cfg))


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #

def load_features(base: Optional[Path] = None) -> List[Dict[str, Any]]:
    base = base or root()
    data = read_json(base / FEATURES_FILE, default=[])
    if not isinstance(data, list):
        raise HarnessError(f"{FEATURES_FILE} debe ser un array")
    return data


def save_features(features: List[Dict[str, Any]], base: Optional[Path] = None) -> None:
    write_json((base or root()) / FEATURES_FILE, features)


def find_feature(features: List[Dict[str, Any]], fid: str) -> Dict[str, Any]:
    for feat in features:
        if feat.get("id") == fid:
            return feat
    raise HarnessError(f"No existe la feature {fid}")


def active_feature(features: Optional[List[Dict[str, Any]]] = None,
                   base: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """La (única) feature en una fase activa, o None."""
    feats = features if features is not None else load_features(base)
    act = [f for f in feats if f.get("status") in ACTIVE_PHASES]
    if len(act) > 1:
        ids = ", ".join(f["id"] for f in act)
        raise HarnessError(f"Invariante roto: varias features activas ({ids})")
    return act[0] if act else None


# --------------------------------------------------------------------------- #
# Eventos (métricas y auditoría)
# --------------------------------------------------------------------------- #

def log_event(kind: str, base: Optional[Path] = None, **data: Any) -> None:
    base = base or root()
    path = base / EVENTS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": now(), "event": kind, **data}, ensure_ascii=False) + "\n")
    except OSError:
        pass  # el log nunca debe romper el flujo


def read_events(base: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = (base or root()) / EVENTS_FILE
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


# --------------------------------------------------------------------------- #
# Git
# --------------------------------------------------------------------------- #

def git(args: List[str], base: Optional[Path] = None) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["git"] + args, cwd=str(base or root()),
                              capture_output=True, text=True, timeout=60)
        return proc.returncode, (proc.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def changed_files(feature: Dict[str, Any], base: Optional[Path] = None) -> List[str]:
    """Ficheros cambiados desde el commit base de la feature (incluye sin trackear)."""
    base = base or root()
    files: Set[str] = set()
    base_commit = feature.get("base_commit")
    if base_commit:
        rc, out = git(["diff", "--name-only", base_commit], base)
        if rc == 0:
            files.update(x for x in out.splitlines() if x)
    else:
        rc, out = git(["diff", "--name-only", "HEAD"], base)
        if rc == 0:
            files.update(x for x in out.splitlines() if x)
    rc, out = git(["ls-files", "--others", "--exclude-standard"], base)
    if rc == 0:
        files.update(x for x in out.splitlines() if x)
    return sorted(files)


def product_changes(feature: Dict[str, Any], cfg: Dict[str, Any],
                    base: Optional[Path] = None) -> List[str]:
    return [f for f in changed_files(feature, base) if in_package(f, cfg)]


# --------------------------------------------------------------------------- #
# Hash del árbol de fuente: ata la evidencia al código exacto que se verificó
# --------------------------------------------------------------------------- #

def tree_hash(cfg: Optional[Dict[str, Any]] = None, base: Optional[Path] = None) -> str:
    base = base or root()
    cfg = cfg or load_config(base)
    digest = hashlib.sha256()
    for pkg in package_dirs(cfg):
        top = base / pkg
        if not top.exists():
            continue
        for path in sorted(p for p in top.rglob("*") if p.is_file()):
            if path.name == ".gitkeep" or "node_modules" in path.parts:
                continue
            digest.update(str(path.relative_to(base)).replace("\\", "/").encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Clasificación de metadata -> tipos de cambio
# --------------------------------------------------------------------------- #

_KIND_RULES: List[Tuple[str, str]] = [
    (r"/classes/[^/]*Test\.cls(-meta\.xml)?$", "apex-test"),
    (r"/classes/TestDataFactory[^/]*\.cls(-meta\.xml)?$", "apex-test"),
    (r"/classes/[^/]+\.cls(-meta\.xml)?$", "apex"),
    (r"/triggers/[^/]+\.trigger(-meta\.xml)?$", "apex"),
    (r"/lwc/[^/]+/__tests__/", "lwc-test"),
    (r"/lwc/", "lwc"),
    (r"/aura/", "lwc"),
    (r"/flows/|/flowDefinitions/", "flow"),
    (r"/(permissionsets|permissionsetgroups|sharingRules|customPermissions|profiles|roles|groups|queues)/",
     "permissions"),
    (r"/(namedCredentials|externalCredentials|externalServiceRegistrations|remoteSiteSettings|"
     r"cspTrustedSites|platformEventChannels|platformEventChannelMembers|connectedApps|externalClientApps)/",
     "integration"),
    (r"/objects/[^/]+__e/", "integration"),
    (r"/(aiAuthoringBundles|genAiPlugins|genAiFunctions|genAiPlannerBundles|genAiPromptTemplates|"
     r"bots|aiEvaluationDefinitions)/", "agentforce"),
    (r"/(objects|customMetadata|globalValueSets|standardValueSets)/", "data-model"),
    (r"/(layouts|flexipages|tabs|applications|quickActions|labels|email|staticresources|"
     r"messageChannels|pathAssistants|reports|dashboards)/", "ui-config"),
    # Respaldo por carpeta: sirve para globs de scope sin extensión (".../classes/Pedido*").
    (r"/classes/[^/]*Test[^/]*$", "apex-test"),
    (r"/classes/|/triggers/", "apex"),
]


def classify(path: str) -> str:
    probe = "/" + path.replace("\\", "/")
    for rx, kind in _KIND_RULES:
        if re.search(rx, probe):
            return kind
    return "other"


def kinds_of(paths: Iterable[str]) -> Set[str]:
    return {classify(p) for p in paths}


def kinds_of_scope(globs: Iterable[str]) -> Set[str]:
    """Aproxima los tipos a partir de los globs del scope (antes de que existan ficheros)."""
    return {classify_glob(pat) for pat in globs if not pat.startswith("!")}


def classify_glob(pattern: str) -> str:
    return classify(pattern.replace("**", "x").replace("*", "x") + ("x" if pattern.endswith("/") else ""))


# --------------------------------------------------------------------------- #
# Pipeline derivado: qué roles, gates y reviews exige un conjunto de cambios
# --------------------------------------------------------------------------- #

def load_pipeline(base: Optional[Path] = None) -> Dict[str, Any]:
    return read_json((base or root()) / PIPELINE_FILE)


def load_roles(base: Optional[Path] = None) -> Dict[str, Any]:
    return read_json((base or root()) / ROLES_FILE)


def derive_plan(kinds: Set[str], size: str, pipeline: Dict[str, Any]) -> Dict[str, List[str]]:
    """Para cada sección del pipeline (design, build, gates, reviews, release,
    release_gates) devuelve, en orden canónico, lo que exigen estos cambios."""
    kinds = set(kinds) - {"other"}
    plan: Dict[str, List[str]] = {}
    for section, order in pipeline["order"].items():
        wanted: Set[str] = set()
        for rule in pipeline.get(section, []):
            sizes = rule.get("sizes")
            if sizes and size not in sizes:
                continue
            when = rule.get("when", "always")
            if when == "always":
                hit = True
            elif when == "any-product":
                hit = bool(kinds)
            else:
                hit = bool(kinds & set(when))
            if hit:
                wanted.update(rule["use"])
        plan[section] = [x for x in order if x in wanted]
    return plan


# --------------------------------------------------------------------------- #
# Evidencia
# --------------------------------------------------------------------------- #

def evidence_dir(fid: str, base: Optional[Path] = None) -> Path:
    return (base or root()) / EVIDENCE_DIR / fid


def write_evidence(fid: str, name: str, data: Dict[str, Any], base: Optional[Path] = None) -> Path:
    path = evidence_dir(fid, base) / f"{name}.json"
    write_json(path, data)
    return path


def read_evidence(fid: str, name: str, base: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = evidence_dir(fid, base) / f"{name}.json"
    if not path.exists():
        return None
    try:
        return read_json(path)
    except HarnessError:
        return None


def evidence_status(fid: str, name: str, current_tree: str,
                    base: Optional[Path] = None) -> Tuple[str, str]:
    """('pass'|'fail'|'stale'|'missing', detalle)."""
    ev = read_evidence(fid, name, base)
    if ev is None:
        return "missing", "sin evidencia"
    if ev.get("tree_hash") != current_tree:
        return "stale", f"evidencia de otro árbol ({ev.get('tree_hash')} ≠ {current_tree}); hay que repetir"
    if ev.get("status") == "pass":
        return "pass", ev.get("summary", "")
    return "fail", ev.get("summary", "")


# --------------------------------------------------------------------------- #
# Informes de handoff
# --------------------------------------------------------------------------- #

def report_path(fid: str, role: str, base: Optional[Path] = None) -> Path:
    return (base or root()) / "progress" / fid / f"{role}.md"


def spec_dir(fid: str, base: Optional[Path] = None) -> Path:
    return (base or root()) / "docs" / "specs" / fid


def missing_headings(path: Path, headings: Iterable[str]) -> List[str]:
    if not path.exists():
        return list(headings)
    text = path.read_text(encoding="utf-8", errors="replace")
    found = {m.group(1).strip().lower() for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", text, re.M)}
    return [h for h in headings if not any(f.startswith(h.lower()) for f in found)]
