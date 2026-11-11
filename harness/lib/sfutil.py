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


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "test-classes":
        print("\n".join(test_classes(sys.argv[2:])))
    else:
        sys.exit("uso: sfutil.py test-classes <packageDir>...")
