#!/usr/bin/env python3
"""PostToolUse (Write | Edit | MultiEdit): revisión instantánea del fichero recién
escrito. Detecta en segundos los errores típicos de Salesforce que, si no, se
descubrirían minutos después en un gate (o en producción).

Son comprobaciones heurísticas y baratas; no sustituyen a Code Analyzer ni a los
revisores. Devuelven el hallazgo al agente (exit 2) para que lo corrija o lo
justifique en su informe.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple

import _hx
from _hx import core

Finding = Tuple[int, str]  # (línea, mensaje)

# --------------------------------------------------------------------------- #
# Apex
# --------------------------------------------------------------------------- #

def blank_noise(src: str) -> str:
    """Sustituye comentarios y literales de texto por espacios, conservando líneas y posiciones."""
    out, i, n = [], 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif src[i] == "'":
            j = i + 1
            while j < n and src[j] != "'":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append("'" + re.sub(r"[^\n]", " ", src[i + 1:j - 1]) + ("'" if j - 1 > i else ""))
            i = j
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


_TOKEN = re.compile(
    r"(?P<loop>\b(?:for|while)\b)|(?P<do>\bdo\b)|(?P<open>\{)|(?P<close>\})|(?P<lp>\()|(?P<rp>\))|(?P<semi>;)"
    r"|(?P<soql>\[\s*(?:SELECT|FIND)\b)"
    r"|(?P<db>\bDatabase\s*\.\s*(?:query|queryWithBinds|countQuery|getQueryLocator|insert|update|upsert|delete|"
    r"undelete|merge|convertLead|executeBatch)\b)"
    r"|(?P<dml>(?<![.\w])(?:insert|update|upsert|delete|undelete|merge)\s+(?!as\b)[A-Za-z_\[(])"
    r"|(?P<async>\bSystem\s*\.\s*enqueueJob\b|\bMessaging\s*\.\s*sendEmail\b|\bEventBus\s*\.\s*publish\b)",
    re.I)


def loop_findings(clean: str) -> List[Finding]:
    """SOQL / DML / encolados dentro de bucles (incluye cuerpos de una sola sentencia)."""
    findings: List[Finding] = []
    stack: List[bool] = []
    expect_header = in_header = pending_loop = False
    header_depth = 0
    prev = "semi"
    for m in _TOKEN.finditer(clean):
        kind = m.lastgroup or ""
        line = clean.count("\n", 0, m.start()) + 1
        if kind == "loop":
            expect_header = True
        elif kind == "do":
            pending_loop = True
        elif kind == "lp":
            if expect_header and not in_header:
                in_header, header_depth, expect_header = True, 1, False
            elif in_header:
                header_depth += 1
        elif kind == "rp":
            if in_header:
                header_depth -= 1
                if header_depth == 0:
                    in_header, pending_loop = False, True
        elif kind == "open":
            stack.append(pending_loop)
            pending_loop = False
        elif kind == "close":
            if stack:
                stack.pop()
            pending_loop = False
        elif kind == "semi":
            if not in_header:
                pending_loop = False
        else:
            inside = any(stack) or (pending_loop and not in_header)
            if kind == "dml" and prev not in ("semi", "open", "close", "rp", "do"):
                inside = False  # no está en posición de sentencia: no es DML
            if inside:
                label = {"soql": "consulta SOQL/SOSL", "db": "operación Database.*", "dml": "DML",
                         "async": "encolado/envío"}[kind]
                findings.append((line, f"{label} dentro de un bucle: sácalo fuera y opera sobre colecciones "
                                       "(límites de gobierno)."))
        prev = kind
    return findings


_HARD_ID = re.compile(r"'(?:00[1-9A-Za-z]|0[1-9A-Z][0-9A-Za-z]|a[0-9A-Za-z]{2})[0-9A-Za-z]{12}(?:[0-9A-Za-z]{3})?'")


def check_apex(path: Path, src: str) -> List[Finding]:
    findings: List[Finding] = []
    clean = blank_noise(src)
    lines = src.splitlines()
    is_trigger = path.suffix == ".trigger"
    is_test = bool(re.search(r"@isTest", clean, re.I))

    def line_of(pos: int) -> int:
        return clean.count("\n", 0, pos) + 1

    findings += loop_findings(clean)

    decl = re.search(r"\b(?:public|global|private)?\s*((?:virtual|abstract|with\s+sharing|without\s+sharing|"
                     r"inherited\s+sharing)\s+)*\b(class|interface|enum)\s+(\w+)([^{]*)\{", clean, re.I)
    if decl and not is_trigger and decl.group(2).lower() == "class" and not is_test:
        header = decl.group(0)
        if not re.search(r"\b(with|without|inherited)\s+sharing\b", header, re.I) \
                and not re.search(r"\bextends\s+Exception\b", header, re.I):
            findings.append((line_of(decl.start()), "La clase no declara sharing. Usa `with sharing` (o `inherited "
                                                    "sharing` en utilidades); `without sharing` solo justificado."))
    for m in re.finditer(r"\bwithout\s+sharing\b", clean, re.I):
        ln = line_of(m.start())
        context = "\n".join(lines[max(0, ln - 6):ln])
        if not re.search(r"justificaci[oó]n|justification", context, re.I):
            findings.append((ln, "`without sharing` sin justificar: añade encima un comentario "
                                 "`// JUSTIFICACIÓN: …` y que conste en el diseño."))
    for m in re.finditer(r"SeeAllData\s*=\s*true", clean, re.I):
        findings.append((line_of(m.start()), "`SeeAllData=true` está prohibido: crea los datos con TestDataFactory."))
    for m in _HARD_ID.finditer(src):
        ln = src.count("\n", 0, m.start()) + 1
        if not lines[ln - 1].lstrip().startswith("//"):
            findings.append((ln, "Id de Salesforce en el código: los Ids cambian entre orgs. Consulta por "
                                 "DeveloperName / Custom Metadata."))
    for m in re.finditer(r"\bDatabase\s*\.\s*(?:query|countQuery|getQueryLocator)\s*\(([^;]*);", clean, re.I):
        stmt = src[m.start():m.end()]
        if "+" in m.group(1) and "escapeSingleQuotes" not in stmt:
            findings.append((line_of(m.start()), "SOQL dinámico concatenado: usa bind variables "
                                                 "(`Database.queryWithBinds`) o `String.escapeSingleQuotes`."))
    for m in re.finditer(r"@SuppressWarnings|NOPMD", src):
        findings.append((src.count("\n", 0, m.start()) + 1,
                         "Supresión de regla de análisis: solo con justificación en el informe del implementer."))
    if is_test and not is_trigger and re.search(r"\bstatic\s+void\b|\btestMethod\b", clean, re.I) \
            and not re.search(r"\bAssert\s*\.|\bSystem\s*\.\s*assert", clean, re.I):
        findings.append((1, "Clase de test sin ninguna aserción: un test que no comprueba nada no es un test."))
    if is_trigger:
        body = clean[clean.find("{") + 1: clean.rfind("}")] if "{" in clean else ""
        if body.count(";") > 2 or re.search(r"\b(for|while|if)\s*\(", body):
            findings.append((1, "Lógica en el cuerpo del trigger: el trigger solo instancia su handler y delega "
                                "(`new XTriggerHandler().run();`)."))
    return findings


# --------------------------------------------------------------------------- #
# Metadata XML, LWC, JSON
# --------------------------------------------------------------------------- #

_BROAD_PERMS = re.compile(r"<name>(ModifyAllData|ViewAllData|ModifyMetadata|AuthorApex|ManageUsers|"
                          r"CustomizeApplication)</name>")


def check_xml(path: Path, src: str) -> List[Finding]:
    findings: List[Finding] = []
    try:
        ET.fromstring(src.encode("utf-8"))
    except ET.ParseError as exc:
        return [(exc.position[0], f"XML mal formado: {exc}. Así no despliega.")]
    probe = "/" + str(path).replace("\\", "/")
    if "/profiles/" in probe:
        findings.append((1, "No se versionan perfiles: el acceso se concede con permission sets."))
    if "/permissionsets/" in probe:
        for m in _BROAD_PERMS.finditer(src):
            findings.append((src.count("\n", 0, m.start()) + 1,
                             f"Permiso de sistema amplio ({m.group(1)}) en un permission set: mínimo privilegio; "
                             "solo con justificación explícita en el diseño."))
        for m in re.finditer(r"<(viewAllRecords|modifyAllRecords)>true</", src):
            findings.append((src.count("\n", 0, m.start()) + 1,
                             f"`{m.group(1)}` salta el sharing del objeto: justifícalo en el diseño o quítalo."))
    if "/flows/" in probe and re.search(r"<processType>Workflow</processType>", src):
        findings.append((1, "Esto es un Process Builder (legado). Solo Flows."))
    return findings


def check_lwc(path: Path, src: str) -> List[Finding]:
    findings: List[Finding] = []
    if "__tests__" in path.parts:
        return findings

    def add(rx: str, msg: str, flags: int = 0) -> None:
        for m in re.finditer(rx, src, flags):
            findings.append((src.count("\n", 0, m.start()) + 1, msg))

    if path.suffix == ".js":
        add(r"\bconsole\.(log|debug)\s*\(", "`console.log` olvidado en un componente.")
        add(r"\.innerHTML\s*=", "`innerHTML` abre la puerta a XSS: usa el template o `lwc:dom=\"manual\"` con cuidado.")
        add(r"\beval\s*\(", "`eval` no está permitido (Lightning Web Security / CSP).")
        add(r"\bdocument\.(querySelector|getElementById)", "No consultes `document`: usa `this.template.querySelector` "
                                                             "o `this.refs`.")
        add(r"\bwindow\.location\b", "Navega con `NavigationMixin`, no con `window.location`.")
    if path.suffix == ".html":
        add(r"<img\b(?![^>]*\balt=)[^>]*>", "Imagen sin `alt` (accesibilidad).", re.I)
        add(r"<lightning-button-icon\b(?![^>]*\balternative-text=)[^>]*>",
            "`lightning-button-icon` sin `alternative-text` (accesibilidad).", re.I)
        add(r"<lightning-input\b(?![^>]*\blabel=)[^>]*>", "`lightning-input` sin `label` (accesibilidad).", re.I)
        add(r"\sstyle=\"", "Estilos en línea: usa el CSS del componente y design tokens / SLDS.")
    return findings


# --------------------------------------------------------------------------- #

def main() -> None:
    event = _hx.read_event()
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    relp = core.rel(file_path, _hx.PROJECT) if file_path else None
    if not relp:
        return
    path = _hx.PROJECT / relp
    if not path.is_file() or path.stat().st_size > 400_000:
        return
    cfg = core.load_config(_hx.PROJECT)
    src = path.read_text(encoding="utf-8", errors="replace")
    findings: List[Finding] = []

    if path.suffix == ".json":
        try:
            json.loads(src)
        except json.JSONDecodeError as exc:
            findings.append((exc.lineno, f"JSON inválido: {exc.msg}"))
    elif core.in_package(relp, cfg):
        if path.suffix in (".cls", ".trigger"):
            findings = check_apex(path, src)
        elif path.suffix == ".xml":
            findings = check_xml(path, src)
        elif "lwc" in path.parts and path.suffix in (".js", ".html"):
            findings = check_lwc(path, src)

    if not findings:
        return
    findings = sorted(set(findings))[:15]
    core.log_event("quick_check", base=_hx.PROJECT, file=relp, findings=len(findings),
                   role=_hx.role_of(event))
    body = "\n".join(f"  - {relp}:{ln} — {msg}" for ln, msg in findings)
    _hx.feedback(f"[harness:quick-check] Revisión rápida de `{relp}` ({len(findings)} hallazgo(s)):\n{body}\n"
                 "Corrígelo ahora. Si alguno es un falso positivo (la comprobación es heurística), sigue adelante "
                 "y déjalo explicado en la sección Pendiente de tu informe.")


if __name__ == "__main__":
    _hx.safe_main(main)
