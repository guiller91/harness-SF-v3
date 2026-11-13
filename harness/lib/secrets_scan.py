#!/usr/bin/env python3
"""Busca secretos en los ficheros cambiados de la feature. Sin dependencias externas.

    python secrets_scan.py <changed-files.txt> [allowlist]
      exit 0 -> limpio · exit 1 -> hay secretos

Excepciones: `secrets-allowlist.txt` en la raíz (ruta protegida: solo la edita el humano), una por línea:
    <ruta> <huella>        # la huella la imprime este escáner
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

# (id, regex, también en clases de test)
RULES: List[Tuple[str, "re.Pattern[str]", bool]] = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), True),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), True),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), True),
    ("sf-session-id", re.compile(r"\b00D[A-Za-z0-9]{12,15}![A-Za-z0-9._]{40,}"), True),
    ("auth-header-literal", re.compile(
        r"""['"]Authorization['"]\s*,\s*['"](?:Basic|Bearer|Token)\s+[A-Za-z0-9+/=._~-]{8,}['"]""", re.I), True),
    ("basic-auth-literal", re.compile(r"""Blob\.valueOf\(\s*'[^'\s:]{2,}:[^'\s]{3,}'\s*\)"""), False),
    ("hardcoded-credential", re.compile(
        r"""\b\w*(?:password|passwd|pwd|secret|token|api_?key|client_?secret|access_?key)\w*\s*=\s*'[^'\s]{6,}'""",
        re.I), False),
]
TEXT_EXT = (".cls", ".trigger", ".js", ".html", ".xml", ".json", ".yml", ".yaml", ".properties", ".apex", ".page",
            ".component", ".md", ".txt")
PLACEHOLDER = re.compile(r"(?:x{4,}|\*{4,}|changeme|example|dummy|placeholder|fake|test|<[^>]+>|\{!?\$)", re.I)


def is_test(path: str) -> bool:
    return bool(re.search(r"Test[^/]*\.cls$|/__tests__/", path))


def fingerprint(path: str, match: str) -> str:
    return hashlib.sha256(f"{path}\0{match}".encode()).hexdigest()[:12]


def load_allow(path: Path) -> Set[Tuple[str, str]]:
    out: Set[Tuple[str, str]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 2:
                out.add((parts[0].replace("\\", "/"), parts[1]))
    return out


def scan(files: List[str], allow: Set[Tuple[str, str]]) -> List[str]:
    findings = []
    for f in files:
        p = Path(f)
        if not f.endswith(TEXT_EXT) or not p.is_file():
            continue
        rel = f.replace("\\", "/")
        test = is_test(rel)
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for rid, rx, in_tests in RULES:
                if test and not in_tests:
                    continue
                for m in rx.finditer(line):
                    val = m.group(0)
                    if rid in ("hardcoded-credential", "basic-auth-literal") and PLACEHOLDER.search(val.split("=", 1)[-1]):
                        continue
                    fp = fingerprint(rel, val)
                    if (rel, fp) in allow:
                        continue
                    shown = val[:16] + "…"  # nunca el final: ahí está el secreto
                    findings.append(f"  [X] {rid}  {rel}:{n}  {shown}   (huella {fp})")
    return findings


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    changed = Path(sys.argv[1])
    files = [x.strip() for x in changed.read_text(encoding="utf-8").splitlines() if x.strip()] if changed.exists() else []
    allow = load_allow(Path(sys.argv[2]) if len(sys.argv) > 2 else Path("secrets-allowlist.txt"))
    findings = scan(files, allow)
    for line in findings:
        print(line)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
