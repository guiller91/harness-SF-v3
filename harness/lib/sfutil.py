#!/usr/bin/env python3
"""Utilidades de fuente Salesforce para los gates."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_TEST_METHOD = re.compile(
    r"@isTest(\s*\([^)]*\))?\s+(?:(?:public|private|global)\s+)?static\s+void\b|\btestMethod\b", re.I)


def test_classes(pkg_dirs: List[str]) -> List[str]:
    """Clases Apex con al menos un método de test."""
    names = set()
    for d in pkg_dirs:
        for path in Path(d).rglob("*.cls"):
            if "classes" not in path.parts:
                continue
            src = _COMMENTS.sub("", path.read_text(encoding="utf-8", errors="replace"))
            if _TEST_METHOD.search(src):
                names.add(path.stem)
    return sorted(names)


def changed_apex(changed_file: str) -> List[str]:
    """Nombres de las clases y triggers Apex de la lista de ficheros cambiados (uno por línea)."""
    path = Path(changed_file)
    if not path.is_file():
        return []
    names = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().replace("\\", "/")
        if line.endswith((".cls", ".trigger")):
            names.add(Path(line).stem)
    return sorted(names)


def tests_for_changes(changed_file: str, pkg_dirs: List[str]) -> List[str]:
    """Clases de test que cubren lo cambiado: los tests modificados, los que siguen una convención de
    nombre (X -> XTest, X_Test, TestX, XTests) y los que mencionan la clase en su código."""
    changed = changed_apex(changed_file)
    if not changed:
        return []
    tests = test_classes(pkg_dirs)
    lower = {n.lower() for n in changed}
    prod = [n for n in changed if n.lower() not in {x.lower() for x in tests}]
    conventional = set()
    for n in prod:
        conventional |= {f"{n}Test".lower(), f"{n}_Test".lower(), f"{n}Tests".lower(), f"Test{n}".lower(),
                         f"Test_{n}".lower()}
    sources = {}
    for d in pkg_dirs:
        for path in Path(d).rglob("*.cls"):
            if "classes" in path.parts and path.stem in tests:
                sources[path.stem] = _COMMENTS.sub("", path.read_text(encoding="utf-8", errors="replace"))
    selected = set()
    for name in tests:
        if name.lower() in lower or name.lower() in conventional:
            selected.add(name)
            continue
        src = sources.get(name, "")
        if any(re.search(rf"\b{re.escape(n)}\b", src, re.I) for n in prod):
            selected.add(name)
    return sorted(selected)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv[:1] == ["test-classes"] and len(argv) >= 3 and argv[1] == "--changed":
        print("\n".join(tests_for_changes(argv[2], argv[3:])))
    elif argv[:1] == ["test-classes"]:
        print("\n".join(test_classes(argv[1:])))
    elif argv[:1] == ["changed-apex"] and len(argv) == 2:
        print("\n".join(changed_apex(argv[1])))
    else:
        sys.exit("uso: sfutil.py test-classes [--changed <fichero>] <packageDir>... | changed-apex <fichero>")
