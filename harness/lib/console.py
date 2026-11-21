"""Centro de control de `./hx watch`.

Sirve el visor y, salvo con --read-only, una API local para lo que hoy haces en la terminal:
pedir una feature, aprobar, cerrar, desbloquear… y hablar con el orquestador (Claude Code en modo
headless) sin abrir una consola.

Seguridad, en este orden:
  - Solo escucha en 127.0.0.1 y rechaza cualquier Host que no sea el suyo (DNS rebinding).
  - Cada llamada a /api exige la clave de sesión: se genera al arrancar, solo existe en memoria y en el
    enlace que se imprime y se abre en tu navegador. Nunca va al HTML, a disco ni al entorno de Claude.
  - Si llega Origin, tiene que ser el propio. POST solo con application/json (fuerza preflight).
  - Las acciones se ejecutan con `./hx` como proceso propio: pasan por las mismas validaciones que
    en la terminal. Los agentes no pueden lanzar `./hx watch` ni llamar a la API (guard_bash).
  - Al orquestador se le prohíbe ejecutar approve/close (HX_CONSOLE=1): te lo pide en el chat y tú
    pulsas el botón.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import core, settings

MAX_BODY = 64 * 1024
ACTIONS = {"propose", "approve", "start", "close", "block", "unblock", "rework", "reverify"}
NEEDS_REASON = {"block", "rework", "reverify"}
FID = re.compile(r"^F-\d{1,5}$")
UUID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
CONSOLE_PROMPT = (
    "Trabajas desde el centro de control de ./hx watch. El humano no ve la terminal: lee tus mensajes "
    "en el panel. No ejecutes ./hx approve ni ./hx close, ni pidas que el humano los escriba: cuando "
    "toque una puerta humana, termina tu turno con un resumen de lo que debe revisar y dile que pulse "
    "Aprobar o Cerrar en el panel. Cuando te diga que ya lo ha hecho, sigue con ./hx status."
)


# --------------------------------------------------------------------------- #
# Estado para la UI
# --------------------------------------------------------------------------- #

def _feature_view(f: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("id", "title", "status", "size", "type", "priority", "description", "acceptance_criteria",
            "out_of_scope", "blocked_reason", "rework_count", "design_approved_at", "branch", "notes")
    return {k: f.get(k) for k in keys}


def build_state(plan_for: Callable, next_step: Callable) -> Dict[str, Any]:
    cfg = core.load_config()
    features = core.load_features()
    act = core.active_feature(features)
    nxt = ""
    if act:
        try:
            plan, _ = plan_for(act, cfg)
            nxt = next_step(act, cfg, plan)
        except Exception as exc:  # el estado nunca tumba el panel
            nxt = f"(no pude calcular el siguiente paso: {exc})"
    pending: List[Dict[str, Any]] = []
    for f in features:
        fid, st = f["id"], f["status"]
        if st == "draft":
            pending.append({"action": "approve", "id": fid, "label": f"Aprobar {fid}", "kind": "feature"})
        elif st == "approved" and not act:
            pending.append({"action": "start", "id": fid, "label": f"Arrancar {fid}", "kind": "start"})
        elif st == "blocked":
            pending.append({"action": "unblock", "id": fid, "label": f"Desbloquear {fid}", "kind": "blocked"})
    if act and "./hx approve" in nxt:
        pending.append({"action": "approve", "id": act["id"], "label": f"Aprobar el diseño de {act['id']}",
                        "kind": "design"})
    if act and "./hx close" in nxt:
        pending.append({"action": "close", "id": act["id"], "label": f"Cerrar {act['id']} como DONE",
                        "kind": "close"})
    return {"project": cfg.get("project"), "org": (cfg.get("org") or {}).get("targetOrgAlias"),
            "active": act["id"] if act else None, "phase": act["status"] if act else None, "next": nxt,
            "features": [_feature_view(f) for f in features], "pending": pending}


# --------------------------------------------------------------------------- #
# Acciones humanas: se ejecutan con la propia CLI
# --------------------------------------------------------------------------- #

def run_action(body: Dict[str, Any], cli_path: Path) -> Tuple[int, str]:
    action = body.get("action")
    if action not in ACTIONS:
        return 2, f"Acción no permitida: {action!r}"
    base = core.root()
    args: List[str] = [action]
    fid = body.get("id")
    if action == "propose":
        draft = body.get("draft")
        if not isinstance(draft, dict):
            return 2, "Falta el borrador."
        drafts = base / "progress" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        path = drafts / f"ui-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}.json"
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        args.append(str(path))
    else:
        if not isinstance(fid, str) or not FID.match(fid):
            return 2, "Id de feature no válido."
        args.append(fid)
        if action in NEEDS_REASON:
            reason = str(body.get("reason") or "").strip()
            if not reason:
                return 2, "Indica el motivo."
            args += ["--reason", reason[:500]]
        if action == "unblock" and body.get("reset_rework"):
            args.append("--reset-rework")
    env = dict(os.environ)
    env.pop("HARNESS_MAINTENANCE", None)
    env.pop("HX_CONSOLE", None)
    env["HX_ACTOR"] = "human-ui"
    env["HX_ROOT"] = str(base)
    try:
        proc = subprocess.run([sys.executable, str(cli_path), *args], cwd=base, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
        rc, output = proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        rc, output = 3, "La acción tardó demasiado y se canceló."
    core.log_event("human_action", feature=fid if action != "propose" else None, action=action,
                   source="ui", rc=rc)
    return rc, output


# --------------------------------------------------------------------------- #
# Orquestador headless
# --------------------------------------------------------------------------- #

def _short(value: Any, n: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Orchestrator:
    """Una conversación con el orquestador: cada mensaje es un `claude -p` que reanuda la sesión."""

    def __init__(self, base: Path, claude: Optional[str]) -> None:
        self.base = base
        self.claude = claude
        self.lock = threading.Lock()
        self.proc: Optional[subprocess.Popen] = None
        self.dir = base / ".harness" / "console"
        self.session_id: Optional[str] = None
        self.items: List[Dict[str, Any]] = []
        self.stopping = False
        self._load()

    # -- persistencia (la conversación sobrevive a cerrar ./hx watch) --
    def _load(self) -> None:
        try:
            meta = json.loads((self.dir / "session.json").read_text(encoding="utf-8"))
            sid = meta.get("session_id")
            self.session_id = sid if isinstance(sid, str) and UUID.match(sid) else None
        except (OSError, ValueError):
            pass
        try:
            for line in (self.dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.items.append(json.loads(line))
        except (OSError, ValueError):
            self.items = []
        for i, item in enumerate(self.items):
            item["i"] = i

    def _save_meta(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "session.json").write_text(json.dumps({"session_id": self.session_id}), encoding="utf-8")

    def add(self, kind: str, text: str, **extra: Any) -> None:
        with self.lock:
            item = {"i": len(self.items), "at": core.now(), "kind": kind, "text": text, **extra}
            self.items.append(item)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / "transcript.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # -- API --
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def view(self, since: int) -> Dict[str, Any]:
        with self.lock:
            items = self.items[since:] if since >= 0 else list(self.items)
        return {"available": bool(self.claude), "running": self.running, "session": bool(self.session_id),
                "items": items, "total": len(self.items)}

    def send(self, message: str) -> Tuple[int, str]:
        if not self.claude:
            return 3, "No encuentro `claude` en el PATH de esta máquina."
        message = message.strip()
        if not message:
            return 2, "Escribe un mensaje."
        if len(message) > 20000:
            return 2, "Mensaje demasiado largo."
        with self.lock:
            if self.running:
                return 2, "El orquestador está trabajando: espera o pulsa Detener."
            argv = [self.claude, "-p", "--output-format", "stream-json", "--verbose",
                    "--append-system-prompt", CONSOLE_PROMPT]
            if self.session_id:
                argv += ["--resume", self.session_id]
            env = dict(os.environ)
            env.pop("HARNESS_MAINTENANCE", None)
            env["HX_CONSOLE"] = "1"
            env["CLAUDE_PROJECT_DIR"] = str(self.base)
            kw: Dict[str, Any] = {}
            if os.name == "nt":
                kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            else:
                kw["start_new_session"] = True
            try:
                # El mensaje va por stdin, nunca por argv: en Windows `claude.cmd` pasa por cmd.exe.
                self.proc = subprocess.Popen(argv, cwd=self.base, env=env, stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             text=True, encoding="utf-8", errors="replace", **kw)
            except OSError as exc:
                return 3, f"No pude lanzar claude: {exc}"
            self.stopping = False
        self.add("user", message)
        core.log_event("console_message", role="human", chars=len(message))
        proc = self.proc
        threading.Thread(target=self._feed, args=(proc, message), daemon=True).start()
        return 0, "ok"

    def stop(self) -> Tuple[int, str]:
        proc = self.proc
        if not proc or proc.poll() is not None:
            return 2, "No hay nada en marcha."
        self.stopping = True
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            proc.terminate()
        return 0, "Detenido."

    def reset(self) -> Tuple[int, str]:
        if self.running:
            return 2, "Detén al orquestador antes de empezar otra conversación."
        with self.lock:
            self.session_id = None
            self.items = []
        try:
            self._save_meta()
            (self.dir / "transcript.jsonl").write_text("", encoding="utf-8")
        except OSError:
            pass
        return 0, "Conversación nueva."

    # -- lectura del stream --
    def _feed(self, proc: subprocess.Popen, message: str) -> None:
        err_tail: List[str] = []

        def drain_err() -> None:
            for line in proc.stderr:  # type: ignore[union-attr]
                err_tail.append(line.rstrip())
                del err_tail[:-20]

        threading.Thread(target=drain_err, daemon=True).start()
        try:
            proc.stdin.write(message)  # type: ignore[union-attr]
            proc.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass
        for raw in proc.stdout:  # type: ignore[union-attr]
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            self._handle(msg)
        rc = proc.wait()
        if self.stopping:
            self.add("info", "Detenido por el humano.")
        elif rc != 0:
            tail = "\n".join(t for t in err_tail if t)[-800:]
            self.add("error", f"claude terminó con código {rc}." + (f"\n{tail}" if tail else ""))

    def _handle(self, msg: Dict[str, Any]) -> None:
        kind = msg.get("type")
        sid = msg.get("session_id")
        if isinstance(sid, str) and UUID.match(sid) and sid != self.session_id:
            self.session_id = sid
            self._save_meta()
        if kind == "assistant":
            for block in (msg.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    self.add("assistant", block["text"].strip())
                elif block.get("type") == "tool_use":
                    self.add("tool", self._describe_tool(block.get("name", ""), block.get("input") or {}))
        elif kind == "user":
            for block in (msg.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                    self.add("tool-error", _short(content, 300))
        elif kind == "result":
            secs = (msg.get("duration_ms") or 0) / 1000
            usage = msg.get("usage") or {}
            try:
                act = core.active_feature()
            except Exception:  # noqa: BLE001
                act = None
            core.log_event("console_run", feature=act["id"] if act else None,
                           cost_usd=round(float(msg.get("total_cost_usd") or 0), 4), duration_s=round(secs, 1),
                           turns=msg.get("num_turns"), input_tokens=usage.get("input_tokens"),
                           output_tokens=usage.get("output_tokens"), ok=not msg.get("is_error"))
            if msg.get("is_error") or msg.get("subtype") not in (None, "success"):
                self.add("error", _short(msg.get("result") or msg.get("subtype") or "error", 400))
            else:
                self.add("done", f"Turno terminado · {secs:.0f} s")

    @staticmethod
    def _describe_tool(name: str, data: Dict[str, Any]) -> str:
        if name == "Bash":
            return f"$ {_short(data.get('command', ''))}"
        if name in ("Task", "Agent"):
            who = data.get("subagent_type") or "agente"
            return f"→ {who}: {_short(data.get('description') or data.get('prompt', ''), 120)}"
        if name in ("Read", "Write", "Edit"):
            return f"{name} {data.get('file_path', '')}"
        if name in ("Grep", "Glob"):
            return f"{name} {_short(data.get('pattern', ''), 80)}"
        return name


# --------------------------------------------------------------------------- #
# Marca: el logo lo pone cada proyecto en .harness/brand/ (no viaja en el repo del harness)
# --------------------------------------------------------------------------- #

LOGO_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg"}


def brand_logo(base: Path) -> Optional[Tuple[Path, str]]:
    for ext, ctype in LOGO_TYPES.items():
        path = base / ".harness" / "brand" / f"logo{ext}"
        if path.is_file() and path.stat().st_size < 2 * 1024 * 1024:
            return path, ctype
    return None


# --------------------------------------------------------------------------- #
# Servidor
# --------------------------------------------------------------------------- #

def serve(port: int, read_only: bool, cli_path: Path, plan_for: Callable, next_step: Callable,
          on_ready: Callable[[str], None], metrics_fn: Callable[[], Dict[str, Any]] = dict,
          report_fn: Callable[[str], str] = lambda fid: "") -> None:
    base = core.root()
    viewer = base / "harness" / "viewer" / "index.html"
    events = base / core.EVENTS_FILE
    token = secrets.token_urlsafe(24)
    orch = None if read_only else Orchestrator(base, shutil.which("claude"))
    action_lock = threading.Lock()
    logins = settings.LoginJobs()
    tickets: Dict[str, Tuple[str, float]] = {}   # pase temporal para abrir un informe en otra pestaña
    planners = {"/api/config/environments": lambda b: (settings.config_path(), *settings.plan_environments(b), "environments"),
                "/api/config/policies": lambda b: (settings.config_path(), *settings.plan_policies(b), "policies"),
                "/api/config/agent": lambda b: (*settings.plan_agent(b), "agent")}

    class Handler(BaseHTTPRequestHandler):
        server_version = "hx-watch"
        sys_version = ""

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: Any) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            p = self.server.server_address[1]
            return self.headers.get("Host", "") in (f"127.0.0.1:{p}", f"localhost:{p}")

        def _api_ok(self) -> bool:
            if read_only or orch is None:
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                return False
            given = self.headers.get("X-HX-Token", "")
            return secrets.compare_digest(given.encode(), token.encode())

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._get()
            except Exception as exc:  # noqa: BLE001 - nunca cortar la conexión sin respuesta
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._post()
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"rc": 9, "output": f"Error interno: {type(exc).__name__}: {exc}"})

        def _get(self) -> None:
            if not self._host_ok():
                return self._send(403, b"host no permitido", "text/plain; charset=utf-8")
            path, _, query = self.path.partition("?")
            if path in ("/", "/index.html"):
                return self._send(200, viewer.read_bytes(), "text/html; charset=utf-8")
            if path == "/assets/robot.glb":
                glb = base / "harness" / "viewer" / "assets" / "robot.glb"
                if glb.is_file():
                    return self._send(200, glb.read_bytes(), "model/gltf-binary")
                return self._send(404, b"no encontrado", "text/plain; charset=utf-8")
            if path.startswith("/report/"):
                tk = path[len("/report/"):]
                entry = tickets.get(tk)
                if not entry or entry[1] < time.time():
                    return self._send(404, "<h3>Este enlace de informe ha caducado. Ábrelo otra vez desde el panel.</h3>".encode("utf-8"),
                                      "text/html; charset=utf-8")
                fid = entry[0]
                try:
                    page = report_fn(fid)
                except Exception as exc:  # noqa: BLE001
                    from . import report as _report
                    page = _report.error_page(fid, exc)
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/brand/logo":
                found = brand_logo(base)
                if found:
                    return self._send(200, found[0].read_bytes(), found[1])
                return self._send(404, b"sin logo", "text/plain; charset=utf-8")
            if path == "/events.jsonl":
                return self._send(200, events.read_bytes() if events.exists() else b"", "text/plain; charset=utf-8")
            if path.startswith("/api/"):
                if not self._api_ok():
                    return self._json(403, {"error": "clave de sesión no válida"})
                if path == "/api/state":
                    try:
                        return self._json(200, build_state(plan_for, next_step))
                    except Exception as exc:
                        return self._json(500, {"error": str(exc)})
                if path == "/api/config":
                    return self._json(200, {**settings.view_config(), "agents": settings.list_agents(),
                                            "skills": settings.available_skills(), "skillsInfo": settings.skills_info(),
                                            "history": settings.history()})
                if path == "/api/orgs":
                    return self._json(200, settings.list_orgs())
                if path == "/api/orgs/login":
                    m = re.search(r"(?:^|&)job=(L\d+)", query)
                    return self._json(200, logins.view(m.group(1) if m else ""))
                if path == "/api/metrics":
                    return self._json(200, metrics_fn())
                if path == "/api/report":
                    m = re.search(r"(?:^|&)id=(F-\d{1,5})", query)
                    if not m:
                        return self._json(400, {"error": "id no válido"})
                    try:
                        return self._send(200, report_fn(m.group(1)).encode("utf-8"), "text/html; charset=utf-8")
                    except core.HarnessError as exc:
                        return self._json(404, {"error": str(exc)})
                if path == "/api/orch":
                    m = re.search(r"(?:^|&)since=(\d+)", query)
                    return self._json(200, orch.view(int(m.group(1)) if m else 0))  # type: ignore[union-attr]
            self._send(404, b"no encontrado", "text/plain; charset=utf-8")

        def _post(self) -> None:
            if not self._host_ok():
                return self._send(403, b"host no permitido", "text/plain; charset=utf-8")
            if not self.path.startswith("/api/"):
                return self._send(404, b"no encontrado", "text/plain; charset=utf-8")
            if not self._api_ok():
                return self._json(403, {"error": "clave de sesión no válida"})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, {"error": "solo application/json"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                return self._json(413, {"error": "petición demasiado grande"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                assert isinstance(body, dict)
            except (ValueError, AssertionError):
                return self._json(400, {"error": "JSON no válido"})
            assert orch is not None
            if self.path == "/api/action":
                with action_lock:
                    rc, output = run_action(body, cli_path)
                return self._json(200, {"rc": rc, "output": output})
            if self.path in planners:
                with action_lock:
                    target, text, err, kind = planners[self.path](body)
                    if err or target is None or text is None:
                        return self._json(200, {"rc": 2, "output": err or "No válido."})
                    old = target.read_text(encoding="utf-8") if target.exists() else ""
                    if body.get("preview"):
                        d = settings.diff(old, text, target.relative_to(core.root()).as_posix())
                        return self._json(200, {"rc": 0, "diff": d, "output": "" if d else "Sin cambios."})
                    rc, output = settings.write_checked(target, text, kind, cli_path, note=str(body.get("name") or ""))
                return self._json(200, {"rc": rc, "output": output})
            if self.path == "/api/config/undo":
                with action_lock:
                    rc, output = settings.undo(str(body.get("backup") or ""), cli_path)
                return self._json(200, {"rc": rc, "output": output})
            if self.path == "/api/report/ticket":
                fid = str(body.get("id") or "")
                if not FID.match(fid):
                    return self._json(200, {"rc": 2, "output": "Id no válido."})
                now = time.time()
                for k in [k for k, v in tickets.items() if v[1] < now]:
                    tickets.pop(k, None)
                tk = secrets.token_urlsafe(18)
                tickets[tk] = (fid, now + 900)
                return self._json(200, {"rc": 0, "url": f"/report/{tk}"})
            if self.path == "/api/orgs/login":
                rc, output, job = logins.start(body)
                return self._json(200, {"rc": rc, "output": output, "job": job})
            if self.path == "/api/orch/send":
                rc, output = orch.send(str(body.get("message") or ""))
            elif self.path == "/api/orch/stop":
                rc, output = orch.stop()
            elif self.path == "/api/orch/reset":
                rc, output = orch.reset()
            else:
                return self._json(404, {"error": "no encontrado"})
            return self._json(200, {"rc": rc, "output": output})

        def log_message(self, *a: Any) -> None:
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise core.HarnessError(f"No se pudo abrir el puerto {port}: {exc}. Prueba con --port <otro>.")
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    on_ready(url if read_only else f"{url}?k={token}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if orch and orch.running:
            orch.stop()
        server.server_close()
