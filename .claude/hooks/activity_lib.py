"""Qué está haciendo cada agente, contado para el visor (./hx watch).

Solo se registra un resumen SEGURO: el verbo, el sitio de la oficina y, como mucho, un nombre de fichero
o de gate. Nunca argumentos de comandos, contenido de ficheros, prompts ni patrones de búsqueda: un
comando puede llevar un token y `events.jsonl` no es sitio para eso.
"""
from __future__ import annotations

import re
import shlex
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

#: (prefijo de tokens, verbo, sitio). Sitio: "desk" (su mesa) · "server" (sala de servidores, la org).
SF_RULES = [
    (("project", "deploy"), "despliega en la org", "server"),
    (("project", "retrieve"), "descarga metadata de la org", "server"),
    (("project", "generate"), "genera metadata", "desk"),
    (("apex", "run", "test"), "ejecuta tests Apex en la org", "server"),
    (("apex", "get", "test"), "recoge resultados de tests", "server"),
    (("apex", "run"), "ejecuta Apex anónimo en la org", "server"),
    (("data",), "consulta datos de la org", "server"),
    (("sobject",), "estudia el modelo de datos de la org", "server"),
    (("agent", "test"), "prueba el agente en la org", "server"),
    (("agent",), "trabaja con Agentforce", "server"),
    (("code-analyzer",), "pasa el análisis estático", "desk"),
    (("org", "list"), "comprueba las orgs", "desk"),
    (("lightning",), "genera un componente", "desk"),
    (("flow",), "trabaja con flows", "desk"),
]
HX_VERBS = {"status": "consulta el estado", "plan": "revisa el plan", "verdict": "firma su veredicto",
            "advance": "pasa de fase", "start": "abre la feature", "propose": "registra el borrador",
            "scope": "fija el alcance", "rework": "devuelve a construcción", "reverify": "repite verificación",
            "metrics": "mira las métricas", "doctor": "revisa el entorno", "check": "revisa el harness"}
READ_TOOLS = {"cat", "head", "tail", "less", "wc", "ls", "find", "grep", "rg", "tree"}
SAFE_NAME = re.compile(r"^[\w.-]{1,40}$")


def _tokens(segment: str) -> list:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def describe_bash(cmd: str) -> Optional[Tuple[str, str]]:
    for segment in re.split(r"&&|\|\||;|\|", cmd):
        toks = _tokens(segment.strip())
        while toks and re.match(r"^\w+=", toks[0]):  # VAR=valor delante
            toks = toks[1:]
        if not toks:
            continue
        head = toks[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if head in ("cd", "echo", "true", "set", "export"):
            continue
        if head in ("sf", "sfdx"):
            rest = [t for t in toks[1:] if not t.startswith("-")]
            for prefix, verb, place in SF_RULES:
                if tuple(rest[: len(prefix)]) == prefix:
                    return verb, place
            return "usa la CLI de Salesforce", "server"
        if head == "hx":
            sub = toks[1] if len(toks) > 1 else ""
            if sub == "gate":
                name = next((t for t in toks[2:] if not t.startswith("-") and t != "run"), "all")
                return (f"lanza el gate {name}" if SAFE_NAME.match(name) else "lanza un gate"), "desk"
            return HX_VERBS.get(sub, "usa ./hx"), "desk"
        if head in ("npx", "npm"):
            joined = " ".join(toks[1:3])
            if "lwc-jest" in joined or "test" in joined:
                return "ejecuta los tests de LWC", "desk"
            if "prettier" in joined:
                return "formatea el código", "desk"
            return "usa npm", "desk"
        if head == "git":
            sub = toks[1] if len(toks) > 1 and SAFE_NAME.match(toks[1]) else ""
            return (f"git {sub}".strip()), "desk"
        if head in READ_TOOLS:
            return "busca en el repositorio", "desk"
        if head in ("python", "python3", "py", "node"):
            return "ejecuta un script", "desk"
        return f"ejecuta {head}" if SAFE_NAME.match(head) else "ejecuta un comando", "desk"
    return None


def _base(path: Any) -> str:
    name = str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name if SAFE_NAME.match(name) else "un fichero"


def describe(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Evento `activity` (o `delegate`) para una llamada a herramienta, o None si no aporta."""
    tool = event.get("tool_name") or ""
    data = event.get("tool_input") or {}
    if tool in ("Bash", "PowerShell"):
        found = describe_bash(str(data.get("command") or ""))
        return {"kind": "activity", "verb": found[0], "place": found[1], "tool": tool} if found else None
    if tool == "Read":
        return {"kind": "activity", "verb": f"lee {_base(data.get('file_path'))}", "place": "desk", "tool": tool}
    if tool in ("Grep", "Glob"):
        return {"kind": "activity", "verb": "busca en el código", "place": "desk", "tool": tool}
    if tool == "WebFetch":
        host = urlsplit(str(data.get("url") or "")).hostname or "la web"
        return {"kind": "activity", "verb": f"consulta {host[:60]}", "place": "desk", "tool": tool}
    if tool == "WebSearch":
        return {"kind": "activity", "verb": "busca documentación", "place": "desk", "tool": tool}
    if tool in ("Task", "Agent"):
        to = str(data.get("subagent_type") or "")
        task = " ".join(str(data.get("description") or "").split())[:140]
        return {"kind": "delegate", "to": to if SAFE_NAME.match(to) else "", "task": task}
    if tool.startswith("mcp__"):
        server = tool.split("__")[1] if tool.count("__") >= 2 else "un conector"
        return {"kind": "activity", "verb": f"usa {server[:40]}", "place": "desk", "tool": "mcp"}
    return None
