#!/usr/bin/env python3
"""PreToolUse (Bash). Cuatro guardas, en este orden:

  1. hx      — quién puede pedir cada transición; las puertas humanas piden confirmación
  2. sf      — seguridad de orgs: solo la org de desarrollo, nunca credenciales ni producción
  3. git     — sin force-push, sin reescribir historia, commits solo del orquestador
  4. ficheros — el shell no es una puerta trasera para saltarse propiedad, fase y scope

Es una barandilla contra errores y derivas de un agente, no un sandbox frente a un
adversario: las formas rebuscadas de invocar un programa no están cubiertas (ver
docs/security-model.md). Si bloquea un falso positivo (p. ej. un texto que solo
MENCIONA un comando), usa Write/Edit para ese fichero o reformula.
"""
from __future__ import annotations

import re
import shlex
from typing import Dict, List, Optional, Tuple

import _hx
from _hx import core

SEP = re.compile(r"&&|\|\||[;\n|&]")

# --------------------------------------------------------------------------- #
# Preparación del comando
# --------------------------------------------------------------------------- #

_COMMIT_MSG = re.compile(
    r"(\bgit\s+commit\b[^;&|\n]*?(?:-m|--message)[= ]\s*)(\"(?:[^\"\\`$]|\\.)*\"|'[^']*')")


def strip_commit_messages(cmd: str) -> str:
    """Los mensajes de commit son texto, no comandos (salvo que lleven sustituciones)."""
    prev = None
    while prev != cmd:
        prev = cmd
        cmd = _COMMIT_MSG.sub(lambda m: m.group(1) + "MSG", cmd, count=1)
    return cmd


def tokens(text: str) -> List[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.replace('"', " ").replace("'", " ").split()


def segments(cmd: str) -> List[str]:
    return [s.strip() for s in SEP.split(cmd) if s.strip()]


def flag_value(toks: List[str], *names: str) -> Optional[str]:
    for i, tok in enumerate(toks):
        for name in names:
            if tok == name and i + 1 < len(toks):
                return toks[i + 1]
            if tok.startswith(name + "="):
                return tok.split("=", 1)[1]
    return None


# --------------------------------------------------------------------------- #
# 1. hx
# --------------------------------------------------------------------------- #

HX_CALL = re.compile(r"(?:^|[\s;&|(`])(?:\./|\S*/)?hx\s+([a-z][\w-]*)([^;&|\n]*)")
ORCHESTRATOR_ONLY = {"propose", "start", "advance", "rework", "scope", "block", "unblock", "org"}
HUMAN_GATES = {"approve", "close"}


def guard_hx(cmd: str, role: str, event: Dict) -> Optional[Tuple[str, str]]:
    if re.search(r"(?:^|[\s;&|(])(?:python3?|py)(?:\.exe)?\s+(?:-\S+\s+)*[^;&|\n]*harness/cli\.py|-m\s+harness\.cli\b", cmd):
        _hx.deny("No invoques harness/cli.py directamente: usa `./hx <comando>`.", "hx-direct", event)
    pending_ask = None
    for match in HX_CALL.finditer(cmd):
        sub, rest = match.group(1), match.group(2)
        if sub in HUMAN_GATES:
            if role != _hx.MAIN_ROLE:
                _hx.deny(f"`./hx {sub}` es una puerta humana y solo la solicita el orquestador.", "human-gate", event)
            what = "aprobar la feature (o su diseño)" if sub == "approve" else "cerrar la feature como DONE"
            pending_ask = (f"Puerta humana: {what} —{rest.strip() or ''}. Confirma solo si has revisado lo que "
                           "el orquestador te ha enseñado.", "human-gate")
        elif sub in ORCHESTRATOR_ONLY and role != _hx.MAIN_ROLE:
            _hx.deny(f"`./hx {sub}` cambia el estado de la feature y solo lo ejecuta el orquestador. Si lo "
                     "necesitas, dilo en tu informe.", "hx-role", event)
        elif sub == "verdict":
            target = (tokens(rest) or [""])[0]
            if target != role:
                _hx.deny(f"Cada revisor registra SU veredicto. Eres `{role}`; no puedes registrar el de "
                         f"`{target}`.", "verdict-role", event)
    return pending_ask


# --------------------------------------------------------------------------- #
# 2. sf — seguridad de orgs
# --------------------------------------------------------------------------- #

# `sf`, `sfdx`, `npx sf` y rutas completas (/c/Users/x/npm/sf): se llame como se llame, es la CLI.
SF_CALL = re.compile(r"(?:^|[\s;&|(`'\"])(?:npx\s+)?(?:[^\s;&|`'\"]*[/\\])?(?:sf|sfdx)['\"]?\s+([^;&|\n`]*)")

_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
_NODE_BIN = re.compile(r"(?:^|[/\\])node(?:\.exe)?$", re.I)
_CLI_ENTRY = re.compile(r"(?:sf[/\\]client[/\\]bin[/\\]\w+\.js|@salesforce[/\\]cli[/\\](?:bin|lib)[/\\][\w./\\-]*\.js)$", re.I)


def guard_sf_direct(cmd: str, event: Dict) -> None:
    """Lanzar la CLI saltándose `sf` (node run.js, sf.cmd) esquiva la clasificación de comandos."""
    for seg in SEP.split(cmd):
        toks = tokens(seg)
        while toks and (_ASSIGN.match(toks[0]) or toks[0] in ("exec", "command", "env")):
            toks = toks[1:]
        if not toks:
            continue
        head = toks[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        direct = head in ("sf.cmd", "sfdx.cmd") or (
            _NODE_BIN.search(toks[0]) and any(_CLI_ENTRY.search(t) for t in toks[1:4]))
        if direct:
            _hx.deny("No lances la CLI de Salesforce saltándote `sf` (node run.js, sf.cmd): los guardas no podrían "
                     "clasificar el comando. Usa `sf ...`; si `sf` falla, díselo al humano.", "sf-direct", event)

HUMAN_ONLY = [
    (("org", "login"), "Las credenciales las gestiona el humano."),
    (("org", "logout"), "Las credenciales las gestiona el humano."),
    (("auth",), "Las credenciales las gestiona el humano."),
    (("org", "display"), "`sf org display` imprime el access token. Usa `sf org list` o `./hx doctor`."),
    (("config", "set"), "La org por defecto la fija el humano; pasa siempre --target-org explícito."),
    (("config", "unset"), "La configuración de la CLI la gestiona el humano."),
    (("alias",), "Los alias de org los gestiona el humano."),
    (("org", "create", "sandbox"), "Crear o refrescar sandboxes es decisión humana."),
    (("org", "refresh"), "Crear o refrescar sandboxes es decisión humana."),
    (("org", "resume"), "Crear o refrescar sandboxes es decisión humana."),
    (("org", "create", "user"), "Los usuarios de la org los gestiona el humano."),
    (("org", "generate", "password"), "Las credenciales las gestiona el humano."),
    (("plugins", "install"), "Instalar plugins de la CLI es decisión humana."),
    (("plugins", "uninstall"), "Instalar plugins de la CLI es decisión humana."),
    (("plugins", "link"), "Instalar plugins de la CLI es decisión humana."),
    (("update",), "Actualizar la CLI es decisión humana."),
]
PACKAGE_MUTATIONS = {"install", "uninstall", "create", "delete", "promote", "update", "convert", "push-upgrade"}
DATA_READS = {"query", "search", "get", "export"}


def topics_of(toks: List[str]) -> List[str]:
    out = []
    for tok in toks:
        if tok.startswith("-"):
            break
        out.append(tok)
    return out


def classify_sf(toks: List[str]) -> str:
    """'local' | 'read' | 'test' | 'check' | 'mutate' | 'scratch-create' | 'scratch-delete'."""
    t = topics_of(toks) + ["", "", ""]
    a, b, c = t[0], t[1], t[2]
    if a == "project":
        if b == "deploy":
            if c in ("validate", "preview", "report"):
                return "check"
            if c == "start" and "--dry-run" in toks:
                return "check"
            return "mutate"
        if b == "delete":
            return "mutate"
        if b == "retrieve":
            return "read"
        return "local"
    if a == "apex":
        if b == "run" and c == "test":
            return "test"
        if b in ("get", "list", "tail"):
            return "read"
        if b == "generate":
            return "local"
        return "mutate"
    if a == "data":
        return "read" if b in DATA_READS else "mutate"
    if a == "org":
        if b == "create" and c == "scratch":
            return "scratch-create"
        if b == "delete":
            return "scratch-delete"
        if b in ("list", "open"):
            return "read"
        return "mutate"
    if a == "agent":
        if b == "generate":
            return "local"
        if b == "validate":
            return "check"
        if b == "test" and c in ("list", "results"):
            return "read"
        if (b == "test" and c in ("run", "resume", "run-eval")) or b == "preview":
            return "test"
        return "mutate"
    if a == "package":
        return "read"
    if a in ("sobject", "schema", "limits"):
        return "read" if a != "schema" or b != "generate" else "local"
    if a in ("code-analyzer", "lightning", "template", "cmdt", "analytics", "plugins", "version", "help",
             "which", "commands", "doctor", "autocomplete", "search", "info", "whatsnew", "static-resource",
             "visualforce"):
        return "local"
    if a in ("api", "force", "community", "flow", "dev"):
        return "mutate"
    return "mutate"  # ante la duda, lo más restrictivo


def guard_sf(cmd: str, role: str, policy: _hx.Policy, event: Dict) -> Optional[Tuple[str, str]]:
    cfg = policy.cfg
    org = cfg["org"]
    target, validation, devhub = org["targetOrgAlias"], org.get("validationOrgAlias") or "", org.get("devHubAlias") or ""
    protected = {a.lower() for a in org.get("protectedAliases", [])}
    allowed = {x for x in (target, validation, devhub) if x}
    spec = policy.roles["roles"].get(role, {})
    role_class = spec.get("class", "guest")
    phase = policy.feature["status"] if policy.feature else None
    pending_ask = None

    for match in SF_CALL.finditer(cmd):
        toks = tokens(match.group(1))
        if not toks:
            continue
        tp = topics_of(toks)
        if not tp:
            continue  # sf --version, sf --help
        shown = "sf " + " ".join(tp[:3])

        for value in toks:
            if value.lower() in protected:
                _hx.deny(f"`{value}` es un alias protegido (producción). Ningún agente ejecuta nada contra él: "
                         "la promoción la hace el pipeline o un humano.", "protected-org", event)
        for prefix, why in HUMAN_ONLY:
            if tuple(tp[:len(prefix)]) == prefix:
                _hx.deny(f"`{shown}` no está permitido a los agentes. {why}", "sf-human-only", event)
        if tp[:1] == ["package"] and (set(tp[1:3]) & PACKAGE_MUTATIONS):
            _hx.deny(f"`{shown}`: instalar, crear o promocionar paquetes es decisión humana.", "sf-human-only", event)
        if "--url-only" in toks or (tp[:2] == ["org", "open"] and "-r" in toks):
            _hx.deny("`--url-only` imprime una URL con sesión. Abre la org sin ese flag.", "sf-secret", event)

        kind = classify_sf(toks)
        if kind == "local":
            continue
        org_flag = flag_value(toks, "--target-org", "-o")
        hub_flag = flag_value(toks, "--target-dev-hub", "-v") if kind == "scratch-create" \
            else flag_value(toks, "--target-dev-hub")
        for value in (org_flag, hub_flag):
            if value and value not in allowed:
                _hx.deny(f"`{shown}` apunta a '{value}', que no es una org del harness. Permitidas: "
                         f"{', '.join(sorted(allowed))}. Las demás no se tocan.", "org-allowlist", event)

        if kind == "scratch-create":
            alias = flag_value(toks, "--alias", "-a")
            if org["model"] != "scratch" or role != _hx.MAIN_ROLE or alias != target:
                _hx.deny(f"La scratch org de desarrollo la crea el orquestador con `./hx org setup` "
                         f"(alias '{target}', org.model=scratch).", "scratch-create", event)
            continue
        if kind == "scratch-delete":
            if org["model"] != "scratch" or tp[:3] != ["org", "delete", "scratch"] or org_flag != target \
                    or role != _hx.MAIN_ROLE:
                _hx.deny("Solo se puede borrar la scratch org de desarrollo, y solo lo pide el orquestador.",
                         "org-delete", event)
            pending_ask = (f"Borrar la scratch org '{target}': se pierde todo lo no guardado en el repo.",
                           "org-delete")
            continue

        if not org_flag and tp[:2] != ["org", "list"]:
            _hx.deny(f"`{shown}` debe llevar `--target-org {target}` explícito. El harness no se fía de la org "
                     "por defecto de la CLI.", "explicit-target", event)
        if org_flag == devhub and devhub and devhub != target and kind != "read":
            _hx.deny(f"El DevHub ('{devhub}') solo se usa para crear scratch orgs.", "org-allowlist", event)

        if kind == "mutate":
            if org_flag != target:
                _hx.deny(f"`{shown}` modifica la org y solo se permite contra la org de desarrollo '{target}'. "
                         f"En '{org_flag}' únicamente validaciones check-only.", "mutate-target", event)
            if role_class != "build":
                _hx.deny(f"`{shown}` modifica la org; solo lo hacen los implementers durante build. "
                         f"Tu rol (`{role}`) es de {role_class}: trabaja en solo lectura o delega.",
                         "mutate-role", event)
            if phase != "build":
                _hx.deny(f"`{shown}` modifica la org, pero la feature está en '{phase}'. Fuera de build la org "
                         "está congelada (rework si hay que corregir).", "mutate-phase", event)
    return pending_ask


# --------------------------------------------------------------------------- #
# 3. git
# --------------------------------------------------------------------------- #

GIT_CALL = re.compile(r"(?:^|[\s;&|(`])git\s+((?:-[cC]\s+\S+\s+)*)([a-z][\w-]*)([^;&|\n]*)")
GIT_READ = {"status", "diff", "log", "show", "blame", "ls-files", "rev-parse", "grep", "describe",
            "shortlog", "cat-file", "ls-tree", "remote", "fetch"}


def guard_git(cmd: str, role: str, policy: _hx.Policy, event: Dict) -> Optional[Tuple[str, str]]:
    pending_ask = None
    protected = set(policy.cfg["git"].get("protectedBranches", []))
    for match in GIT_CALL.finditer(cmd):
        sub, rest = match.group(2), match.group(3)
        toks = tokens(rest)
        if match.group(1).strip():
            _hx.deny("`git -c/-C …` no está permitido: ejecuta git desde la raíz del proyecto y sin overrides.",
                     "git-override", event)
        if sub == "push":
            if any(t in ("-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d") for t in toks) \
                    or any(t.startswith("+") or t.startswith(":") for t in toks):
                _hx.deny("Force-push y borrado de ramas remotas están prohibidos.", "git-force", event)
            if role != _hx.MAIN_ROLE:
                _hx.deny("Solo el orquestador publica ramas.", "git-role", event)
            refs = {t.split(":")[-1] for t in toks if not t.startswith("-")}
            if refs & protected:
                _hx.deny(f"No se hace push directo a {', '.join(sorted(refs & protected))}: se entrega por "
                         "pull request desde la rama de la feature.", "git-protected-branch", event)
            pending_ask = ("Publicar la rama en el remoto (git push).", "git-push")
        elif sub in GIT_READ or (sub == "branch" and not any(t.startswith("-") and t not in ("-a", "-r", "-v", "-vv",
                                                                                           "--list", "--show-current")
                                                               for t in toks)):
            continue
        elif sub in ("rm", "mv"):
            continue  # las rutas las valida la guarda de ficheros
        elif role != _hx.MAIN_ROLE:
            _hx.deny(f"`git {sub}` cambia el repositorio y solo lo ejecuta el orquestador. Tú deja los ficheros "
                     "modificados en el árbol de trabajo y descríbelos en tu informe.", "git-role", event)
        elif sub == "commit" and any(t in ("--no-verify", "-n", "--amend") for t in toks):
            _hx.deny("Sin `--no-verify` ni `--amend`: los commits del harness son aditivos y pasan sus hooks.",
                     "git-commit", event)
        elif sub in ("reset", "clean", "rebase", "filter-branch", "reflog", "gc", "update-ref") \
                or (sub == "checkout" and ("--" in toks or "." in toks)) \
                or (sub == "restore") or (sub == "stash" and toks[:1] in (["drop"], ["clear"])) \
                or (sub == "branch" and any(t in ("-D", "-d", "--delete", "-M", "-m") for t in toks)):
            pending_ask = (f"`git {sub}{rest}` puede descartar trabajo sin commitear o reescribir historia.",
                           "git-destructive")
    return pending_ask


# --------------------------------------------------------------------------- #
# 4. Ficheros desde el shell
# --------------------------------------------------------------------------- #

WRITERS = {"rm", "mv", "cp", "tee", "touch", "truncate", "dd", "install", "ln", "chmod", "chown", "rsync",
           "unlink", "shred", "patch"}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "php", "awk", "bash", "sh", "zsh", "eval", "source",
                ".", "xargs", "env"}
REDIRECT = re.compile(r"(?:\d|&)?>>?\s*([^\s;&|<>()]+)")
PATHISH = re.compile(r"[\w@.~/-]+")


def path_candidates(text: str) -> List[str]:
    return [t for t in tokens(text) if not t.startswith("-") and PATHISH.fullmatch(t)]


def guard_files(cmd: str, role: str, policy: _hx.Policy, event: Dict) -> Optional[Tuple[str, str]]:
    pending_ask = None
    if re.search(r"(?:^|[\s;&|(])sudo\s", cmd):
        _hx.deny("`sudo` no está permitido.", "sudo", event)
    if re.search(r"\b(?:curl|wget)\b[^|;\n]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b", cmd):
        _hx.deny("Descargar y ejecutar scripts (`curl … | sh`) no está permitido.", "pipe-to-shell", event)
    if re.search(r"(?:~|\$HOME|\$\{HOME\}|/home/[\w.-]+|/Users/[\w.-]+|/root)/\.(?:sf|sfdx)\b", cmd) \
            or re.search(r"sfdxAuthUrl|\bSF_ACCESS_TOKEN\b|\bSFDX_ACCESS_TOKEN\b", cmd):
        _hx.deny("Los ficheros y variables de autenticación de la CLI no se leen ni se tocan.", "sf-secret", event)

    def check(path: str, verb: str) -> None:
        nonlocal pending_ask
        relp = core.rel(path, _hx.PROJECT)
        if relp is None:
            return
        if relp in (".", "") or relp == ".git" or relp.startswith(".git/"):
            _hx.deny(f"`{verb}` sobre `{path}` afectaría al proyecto entero o a .git.", "dangerous-path", event)
        if relp in core.package_dirs(policy.cfg):
            _hx.deny(f"`{verb}` sobre el packageDir completo `{relp}` no está permitido.", "dangerous-path", event)
        decision, rule, reason = policy.check_write(role, relp)
        if decision == "deny":
            _hx.deny(f"({verb} desde el shell) {reason}", rule, event)
        if decision == "ask":
            pending_ask = (f"({verb} desde el shell) {reason}", rule)

    for seg in segments(cmd):
        for target in REDIRECT.findall(seg):
            if target not in ("/dev/null", "&1", "&2") and not target.startswith("/dev/"):
                check(target, "redirección")
        toks = tokens(REDIRECT.sub(" ", seg))
        while toks and (re.fullmatch(r"[A-Za-z_]\w*=.*", toks[0]) or toks[0] in ("command", "time", "nohup", "exec")):
            toks = toks[1:]
        if not toks:
            continue
        first = toks[0].split("/")[-1]
        args = [t for t in toks[1:] if not t.startswith("-")]
        writes = first in WRITERS
        if first == "sed" and any(re.fullmatch(r"-[a-zA-Z]*i.*|--in-place.*", t) for t in toks[1:]):
            writes, args = True, args[1:]  # el primer argumento es el script de sed
        if first == "git" and len(toks) > 1 and toks[1] in ("rm", "mv"):
            writes, args = True, [t for t in toks[2:] if not t.startswith("-")]
        if first == "find" and any(t in ("-delete", "-exec", "-execdir", "-ok") for t in toks):
            writes = True
        if first == "npm" and len(toks) > 1 and toks[1] in ("install", "i", "add", "uninstall", "remove", "update") \
                and len(args) > 1:
            pending_ask = ("Cambiar dependencias de npm modifica package.json.", "sensitive-path")
        if writes:
            if first == "rm" and any(t in ("/", "~", "*", "/*", "~/", "$HOME") for t in toks[1:]):
                _hx.deny("`rm` sobre la raíz, el home o un comodín desnudo.", "dangerous-path", event)
            for path in args:
                if PATHISH.fullmatch(path):
                    check(path, first)
        elif first in INTERPRETERS:
            # Un intérprete puede escribir donde quiera: no se le deja nombrar zonas del harness ni producto.
            for path in path_candidates(" ".join(toks[1:])):
                relp = core.rel(path, _hx.PROJECT)
                if relp is None or "/" not in path and not (_hx.PROJECT / path).exists():
                    continue
                if policy.is_protected(relp) and not relp.startswith("harness/gates/"):
                    _hx.deny(f"Un script/intérprete (`{first}`) no puede operar sobre `{relp}`, que es parte del "
                             "harness. Usa `./hx` para el estado y Read para leer.", "protected-path", event)
    return pending_ask


# --------------------------------------------------------------------------- #

def main() -> None:
    event = _hx.read_event()
    if _hx.maintenance():
        return
    cmd = (event.get("tool_input") or {}).get("command") or ""
    if not cmd.strip():
        return
    role = _hx.role_of(event)
    policy = _hx.Policy()
    cleaned = strip_commit_messages(cmd)

    guard_sf_direct(cleaned, event)
    asks = [guard_hx(cleaned, role, event),
            guard_sf(cleaned, role, policy, event),
            guard_git(cleaned, role, policy, event),
            guard_files(cleaned, role, policy, event)]
    for pending in asks:
        if pending:
            _hx.ask(pending[0], pending[1], event)


if __name__ == "__main__":
    _hx.safe_main(main)
