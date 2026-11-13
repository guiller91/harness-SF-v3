#!/usr/bin/env python3
"""Evalúa el resultado de `sf apex run test --json`: tests en verde y cobertura
POR CLASE de las clases/triggers que toca la feature.

Acepta las dos formas que emite la CLI:
  - result.coverage.coverage[]  -> {name, totalLines, totalCovered, coveredPercent}
  - result.codecoverage[]       -> {name, numLinesCovered, numLinesUncovered, percentage}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_result(path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"no se pudo leer {path}: {exc}"
    start = text.find("{")
    if start < 0:
        return None, "la CLI no devolvió JSON"
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError as exc:
        return None, f"JSON inválido de la CLI: {exc}"
    if isinstance(data.get("result"), dict):
        return data["result"], ""
    if "summary" in data:
        return data, ""
    return None, str(data.get("message") or data.get("name") or "respuesta inesperada de la CLI")


def coverage_rows(result: Dict[str, Any]) -> Dict[str, Tuple[float, int]]:
    """nombre -> (porcentaje, líneas totales)."""
    rows: Dict[str, Tuple[float, int]] = {}
    cov = result.get("coverage")
    if isinstance(cov, dict):
        for c in cov.get("coverage") or []:
            total = int(c.get("totalLines") or 0)
            pct = c.get("coveredPercent")
            if pct is None:
                pct = 100.0 * int(c.get("totalCovered") or 0) / total if total else 100.0
            rows[str(c.get("name"))] = (float(pct), total)
    for c in result.get("codecoverage") or []:
        covered = int(c.get("numLinesCovered") or 0)
        total = covered + int(c.get("numLinesUncovered") or 0)
        raw = str(c.get("percentage") or "").rstrip("%")
        try:
            pct = float(raw)
        except ValueError:
            pct = 100.0 * covered / total if total else 100.0
        rows.setdefault(str(c.get("name")), (pct, total))
    return rows


_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)


def needs_coverage(path: Path) -> bool:
    """False para clases de test, interfaces y enums: no tienen líneas que cubrir."""
    try:
        src = _COMMENTS.sub("", path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    head = src[:4000]
    decl = re.search(r"\b(class|interface|enum)\s+\w+", head)
    if not decl:
        return True
    if decl.group(1) in ("interface", "enum"):
        return False
    return not re.search(r"@isTest", head[:decl.start()], re.I)


def changed_units(changed_file: str) -> List[Tuple[str, Path]]:
    units: List[Tuple[str, Path]] = []
    try:
        lines = Path(changed_file).read_text(encoding="utf-8").splitlines()
    except OSError:
        return units
    for line in lines:
        p = Path(line.strip())
        if not line.strip() or not p.exists():
            continue
        if p.suffix == ".cls" and "classes" in p.parts and needs_coverage(p):
            units.append((p.stem, p))
        elif p.suffix == ".trigger" and "triggers" in p.parts:
            units.append((p.stem, p))
    return units


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--changed", required=True)
    ap.add_argument("--gate", type=float, required=True)
    ap.add_argument("--summary", required=True)
    ap.add_argument("--cli-exit", type=int, default=0)
    args = ap.parse_args()

    def finish(code: int, text: str) -> int:
        text = " ".join(text.split())[:300]
        Path(args.summary).write_text(text + "\n", encoding="utf-8")
        return code

    result, err = load_result(args.result)
    if result is None:
        print(f"✗ {err}")
        return finish(3, f"ENTORNO: la ejecución de tests no produjo resultado ({err})")

    summ = result.get("summary") or {}
    ran, failing = int(summ.get("testsRan") or 0), int(summ.get("failing") or 0)
    print(f"Tests: {ran} ejecutados . {summ.get('passing', 0)} en verde . {failing} en rojo . "
          f"outcome={summ.get('outcome')} . cobertura de la ejecución {summ.get('testRunCoverage', '?')}")
    problems: List[str] = []
    for t in result.get("tests") or []:
        outcome = t.get("Outcome") or t.get("outcome")
        if outcome not in ("Pass", "Skip", "Passed"):
            name = t.get("FullName") or t.get("fullName") or "?"
            msg = (t.get("Message") or t.get("message") or "").strip().splitlines()
            print(f"  ✗ {name}: {msg[0] if msg else outcome}")
            stack = (t.get("StackTrace") or t.get("stackTrace") or "").strip()
            if stack:
                print(f"      {stack.splitlines()[0]}")
    if failing or str(summ.get("outcome")) not in ("Passed", "Pass"):
        problems.append(f"{failing} test(s) en rojo")
    if ran == 0:
        problems.append("no se ejecutó ningún test")

    rows = coverage_rows(result)
    units = changed_units(args.changed)
    under: List[str] = []
    print(f"Cobertura por clase de lo que toca la feature (gate {args.gate:g}%):")
    if not units:
        print("  . la feature no cambia clases ni triggers con líneas ejecutables")
    for name, _path in sorted(units):
        if name not in rows:
            print(f"  ✗ {name}: sin cobertura registrada (0%)")
            under.append(f"{name} 0%")
            continue
        pct, total = rows[name]
        if total == 0:
            print(f"  ✓ {name}: sin líneas ejecutables")
        elif pct + 1e-9 < args.gate:
            print(f"  ✗ {name}: {pct:g}% ({total} líneas)")
            under.append(f"{name} {pct:g}%")
        else:
            print(f"  ✓ {name}: {pct:g}% ({total} líneas)")
    if under:
        problems.append(f"bajo el {args.gate:g}%: " + ", ".join(under))

    if problems:
        return finish(1, "; ".join(problems))
    if args.cli_exit != 0:
        return finish(1, f"la CLI terminó con código {args.cli_exit}")
    return finish(0, f"{ran} tests en verde; {len(units)} clase(s)/trigger(s) cambiados >= {args.gate:g}%")


if __name__ == "__main__":
    sys.exit(main())
