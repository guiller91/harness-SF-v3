#!/usr/bin/env python3
"""Prettier del proyecto, invocado con `node <bin de prettier>` (sin npx: en Windows npx.cmd rompe con
rutas con espacios, como sf.cmd).

    python fmt.py check <ficheros...>   -> 0 formateados, 1 alguno sin formatear, 3 prettier no disponible
    python fmt.py write <ficheros...>   -> formatea en sitio
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

EXTS = (".cls", ".trigger", ".js", ".html", ".css")


def prettier_cmd(root: Path) -> Optional[List[str]]:
    pkg = root / "node_modules" / "prettier" / "package.json"
    node = shutil.which("node")
    if not node or not pkg.exists():
        return None
    try:
        bins = json.loads(pkg.read_text(encoding="utf-8")).get("bin")
    except (OSError, ValueError):
        return None
    rel = bins.get("prettier") if isinstance(bins, dict) else bins
    if not rel:
        return None
    return [node, str((pkg.parent / rel).resolve())]


def formattable(files: List[str]) -> List[str]:
    return [f for f in files if f.endswith(EXTS) and Path(f).is_file()]


def run(mode: str, files: List[str], root: Path, timeout: int = 180) -> int:
    files = formattable(files)
    if not files:
        return 0
    cmd = prettier_cmd(root)
    if cmd is None:
        print("[X] prettier no está instalado en el proyecto (npm install).", file=sys.stderr)
        return 3
    try:
        proc = subprocess.run(cmd + ["--" + mode] + files, cwd=str(root), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[X] prettier no se pudo ejecutar: {exc}", file=sys.stderr)
        return 3
    if proc.returncode == 0:
        return 0
    return 1 if mode == "check" else proc.returncode


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "write"):
        print(__doc__)
        sys.exit(2)
    sys.exit(run(sys.argv[1], sys.argv[2:], Path.cwd()))
