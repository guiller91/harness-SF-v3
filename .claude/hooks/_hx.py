"""Base común de los hooks del harness.

Los hooks son la capa de CUMPLIMIENTO: lo que aquí se bloquea no depende de que
un agente recuerde una regla. Regla de diseño: un hook jamás debe romper la
sesión por un fallo propio; ante un error interno deja pasar (exit 0) y lo anota.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional, Tuple

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]).resolve()
os.environ.setdefault("HX_ROOT", str(PROJECT))
sys.path.insert(0, str(PROJECT / "harness"))

from lib import core  # noqa: E402

MAIN_ROLE = "orchestrator"
#: Agentes de solo lectura integrados en Claude Code: se tratan como invitados.
GUEST_AGENTS = {"Explore", "Plan", "general-purpose", "claude", "statusline-setup"}


def read_event() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def role_of(event: Dict[str, Any]) -> str:
    """Rol que ejecuta la acción. La sesión principal es el orquestador."""
    return event.get("agent_type") or MAIN_ROLE


def maintenance() -> bool:
    """HARNESS_MAINTENANCE=1 lo activa un humano para trabajar sobre el propio harness."""
    return os.environ.get("HARNESS_MAINTENANCE") == "1"


def deny(reason: str, rule: str, event: Optional[Dict[str, Any]] = None) -> NoReturn:
    """Bloquea la acción (exit 2: el motivo llega al agente por stderr)."""
    ev = event or {}
    feat = _active_id()
    core.log_event("guard_block", base=PROJECT, rule=rule, role=role_of(ev), feature=feat,
                   tool=ev.get("tool_name", ""), detail=reason[:300])
    print(f"[harness:{rule}] {reason}", file=sys.stderr)
    sys.exit(2)


def ask(reason: str, rule: str, event: Optional[Dict[str, Any]] = None) -> NoReturn:
    """Obliga a pedir confirmación al humano."""
    ev = event or {}
    core.log_event("guard_ask", base=PROJECT, rule=rule, role=role_of(ev), feature=_active_id(),
                   detail=reason[:300])
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": f"[harness:{rule}] {reason}",
    }}, ensure_ascii=False))
    sys.exit(0)


def feedback(message: str) -> NoReturn:
    """PostToolUse / Stop: devuelve el mensaje al agente para que actúe."""
    print(message, file=sys.stderr)
    sys.exit(2)


def _active_id() -> Optional[str]:
    try:
        feat = core.active_feature(base=PROJECT)
        return feat["id"] if feat else None
    except Exception:  # noqa: BLE001
        return None


def safe_main(fn) -> None:
    """Ejecuta el hook; cualquier excepción inesperada se registra y NO bloquea."""
    try:
        fn()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        try:
            core.log_event("hook_error", base=PROJECT, hook=Path(sys.argv[0]).name, error=repr(exc)[:300])
        except Exception:  # noqa: BLE001
            pass
        print(f"[harness] aviso: el hook {Path(sys.argv[0]).name} falló internamente ({exc!r}); "
              "no bloquea, pero avisa al humano.", file=sys.stderr)
        sys.exit(0)


# --------------------------------------------------------------------------- #
# Política de escritura (la comparten guard_write y guard_bash)
# --------------------------------------------------------------------------- #

class Policy:
    def __init__(self) -> None:
        self.cfg = core.load_config(PROJECT)
        self.roles = core.load_roles(PROJECT)
        self.feature = core.active_feature(base=PROJECT)

    # -- clasificación ------------------------------------------------------ #
    def is_protected(self, relp: str) -> bool:
        return core.match_any(relp, self.roles["protected"])

    def is_sensitive(self, relp: str) -> bool:
        return core.match_any(relp, self.roles["sensitive"])

    def is_owned_area(self, relp: str) -> bool:
        """Producto (packageDirs) o zonas con dueño (p. ej. manifest/)."""
        return core.in_package(relp, self.cfg) or core.match_any(relp, self.roles.get("restricted", []))

    def owners(self, relp: str) -> List[str]:
        fid = self.feature["id"] if self.feature else "*"
        out = []
        for name, spec in self.roles["roles"].items():
            globs = core.expand_pkg([g.replace("{fid}", fid) for g in spec.get("write", [])], self.cfg)
            if globs and core.match_any(relp, globs):
                out.append(name)
        return out

    # -- decisión ----------------------------------------------------------- #
    def check_write(self, role: str, relp: str) -> Tuple[str, str, str]:
        """(decisión, regla, motivo) con decisión ∈ allow | ask | deny."""
        if self.is_protected(relp):
            return ("deny", "protected-path",
                    f"`{relp}` forma parte del harness (reglas, gates, estado o evidencia) y ningún agente "
                    "puede modificarlo. El estado se cambia con `./hx`; las reglas las cambia un humano "
                    "(HARNESS_MAINTENANCE=1). Si crees que una regla está mal, díselo al humano.")
        if self.is_sensitive(relp):
            return ("ask", "sensitive-path",
                    f"`{relp}` es configuración del proyecto (dependencias, API version, definición de org). "
                    "Requiere confirmación humana.")
        if not self.is_owned_area(relp):
            return ("allow", "", "")

        feat = self.feature
        if not feat:
            return ("deny", "no-active-feature",
                    f"No hay ninguna feature activa, así que no se toca `{relp}`. Todo cambio de producto pasa "
                    "por una feature aprobada: `./hx status` y, si procede, `./hx propose` → aprobación humana "
                    "→ `./hx start`.")
        spec = self.roles["roles"].get(role)
        fid, phase = feat["id"], feat["status"]
        if role == MAIN_ROLE or not spec or not spec.get("write"):
            owners = ", ".join(self.owners(relp)) or "ningún rol (tipo de metadata no asignado)"
            who = "El orquestador" if role == MAIN_ROLE else f"El rol `{role}`"
            return ("deny", "ownership",
                    f"{who} no escribe aquí. `{relp}` pertenece a: {owners}. Delega en ese agente.")
        if phase not in spec.get("phases", []):
            hint = {
                "design": "El diseño aún no ha pasado su puerta: completa los artefactos y `./hx advance`.",
                "verify": "En verify el código está congelado: lo que se revisa es exactamente lo que se "
                          "verificó. Si hay que corregir, el orquestador ejecuta `./hx rework`.",
                "release": "En release el código está congelado. Un cambio exige `./hx rework`.",
            }.get(phase, "")
            return ("deny", "phase",
                    f"`{role}` solo escribe en fase {'/'.join(spec['phases'])} y {fid} está en '{phase}'. {hint}")
        own = core.expand_pkg([g.replace("{fid}", fid) for g in spec["write"]], self.cfg)
        if not core.match_any(relp, own):
            owners = ", ".join(o for o in self.owners(relp) if o != role) or "ningún rol"
            return ("deny", "ownership",
                    f"`{role}` no es dueño de `{relp}` (dueño: {owners}). No lo edites: anótalo en tu informe "
                    "como pendiente para ese rol y sigue con lo tuyo.")
        if core.in_package(relp, self.cfg):
            scope = core.expand_pkg(feat.get("scope", {}).get("files", []), self.cfg)
            if not core.match_any(relp, scope):
                return ("deny", "scope",
                        f"`{relp}` está fuera del scope aprobado de {fid}. No amplíes el alcance por tu cuenta: "
                        "termina, y en tu informe (sección Pendiente) explica por qué hace falta. El orquestador "
                        f"decide si ejecuta `./hx scope {fid} add <glob> --reason ...`.")
        return ("allow", "", "")


# --------------------------------------------------------------------------- #
# Secretos
# --------------------------------------------------------------------------- #

_SECRET_PATTERNS = [
    (re.compile(r"force://[^\s\"'<>]+@[\w.-]+"), "una Sfdx Auth URL (force://…)"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"), "una clave privada"),
    (re.compile(r"\b00D[A-Za-z0-9]{12,15}![A-Za-z0-9._]{30,}"), "un access token / session id de Salesforce"),
    (re.compile(r"(?i)\b(?:password|passwd|client_?secret|consumer_?secret|api_?key|access_?token|"
                r"refresh_?token|security_?token)\b\s*[:=]\s*['\"](?!\s*['\"])"
                r"(?!\{!|\$\{|<|TODO|CHANGE|XXX|dummy|test|fake|mock|example|placeholder)[^'\"\s]{12,}['\"]"),
     "lo que parece una credencial en claro"),
]


def find_secret(text: str) -> Optional[str]:
    for rx, label in _SECRET_PATTERNS:
        if rx.search(text or ""):
            return label
    return None
