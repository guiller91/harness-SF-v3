"""Utilidades de test: monta una copia aislada del harness en un directorio temporal."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
COPY = [".claude", "harness", "hx", "harness.config.json", "sfdx-project.json", "CLAUDE.md", "AGENTS.md",
        "CHECKPOINTS.md", "code-analyzer.yml", ".gitignore", "package.json"]

STUB_GATE = """#!/usr/bin/env bash
# gate de pruebas: verde salvo que exista .gate-fail-<nombre>
name="$(basename "$0" .sh)"
if [ -f "$HX_ROOT/.gate-fail-$name" ]; then echo "rojo" > "$HX_SUMMARY_FILE"; echo "gate $name ROJO"; exit 1; fi
echo "verde" > "$HX_SUMMARY_FILE"; echo "gate $name verde"
"""


class Project:
    def __init__(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="hx-test-")
        self.root = Path(self.tmp) / "proj"
        self.root.mkdir()
        for name in COPY:
            src = REPO / name
            if not src.exists():
                continue
            dst = self.root / name
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "tests"))
            else:
                shutil.copy2(src, dst)
        (self.root / "feature_list.json").write_text("[]\n", encoding="utf-8")
        (self.root / "force-app/main/default").mkdir(parents=True)
        (self.root / "force-app/main/default/.gitkeep").write_text("")
        for gate in (self.root / "harness/gates").glob("*.sh"):
            if not gate.name.startswith("_"):
                gate.write_text(STUB_GATE, encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    # ------------------------------------------------------------------ #
    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = dict(os.environ)
        env.pop("HARNESS_MAINTENANCE", None)
        env.update({"CLAUDE_PROJECT_DIR": str(self.root), "HX_ROOT": str(self.root)})
        env.update(extra or {})
        return env

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True).stdout

    def hx(self, *args: str) -> Tuple[int, str]:
        proc = subprocess.run([sys.executable, str(self.root / "harness/cli.py"), *args], cwd=self.root,
                              capture_output=True, text=True, env=self.env())
        return proc.returncode, proc.stdout + proc.stderr

    def hook(self, name: str, event: Dict[str, Any], extra_env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
        proc = subprocess.run([sys.executable, str(self.root / ".claude/hooks" / name)], cwd=self.root,
                              input=json.dumps(event), capture_output=True, text=True, env=self.env(extra_env))
        return proc.returncode, proc.stdout, proc.stderr

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def features(self) -> List[Dict[str, Any]]:
        return json.loads((self.root / "feature_list.json").read_text(encoding="utf-8"))

    def feature(self, fid: str = "F-001") -> Dict[str, Any]:
        return next(f for f in self.features() if f["id"] == fid)

    def config(self, **org: Any) -> None:
        path = self.root / "harness.config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["org"].update(org)
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Atajos para llevar una feature hasta una fase
    # ------------------------------------------------------------------ #
    def propose(self, size: str = "S", **over: Any) -> str:
        draft = {"title": "Asignar territorio", "description": "Asignar cuentas por territorio", "size": size,
                 "acceptance_criteria": ["Una cuenta del Norte va a la cola Norte", "Sin territorio va a la cola por defecto"]}
        draft.update(over)
        self.write("progress/drafts/d.json", json.dumps(draft))
        rc, out = self.hx("propose", "progress/drafts/d.json")
        assert rc == 0, out
        return self.features()[-1]["id"]

    def headings(self, heads: List[str]) -> str:
        return "# doc\n" + "".join(f"\n## {h}\ncontenido\n" for h in heads)

    def to_design(self, size: str = "S") -> str:
        fid = self.propose(size)
        assert self.hx("approve", fid)[0] == 0
        rc, out = self.hx("start", fid, "--no-branch")
        assert rc == 0, out
        return fid

    def design_artifacts(self, fid: str, size: str = "S") -> None:
        roles = json.loads((self.root / "harness/roles.json").read_text(encoding="utf-8"))["roles"]
        names = ["solution-architect"] + (["business-analyst", "org-analyst"] if size != "S" else [])
        for name in names:
            art = roles[name]["artifact"]
            self.write(art["path"].replace("{fid}", fid), self.headings(art["headings"]))

    def to_build(self, size: str = "S", scope: Optional[List[str]] = None) -> str:
        fid = self.to_design(size)
        self.design_artifacts(fid, size)
        scope = scope or ["force-app/**/classes/Territorio*"]
        assert self.hx("scope", fid, "set", *scope)[0] == 0
        rc, out = self.hx("advance", fid)
        assert rc == 0, out
        return fid

    def report(self, fid: str, role: str, klass: str = "build", extra: str = "") -> None:
        heads = {"build": ["Resumen", "Archivos", "Verificación", "Pendiente"],
                 "review": ["Veredicto", "Hallazgos"], "release": ["Resumen", "Archivos", "Pendiente"]}[klass]
        self.write(f"progress/{fid}/{role}.md", self.headings(heads) + extra)

    def build_apex(self, fid: str) -> None:
        base = "force-app/main/default/classes"
        self.write(f"{base}/TerritorioService.cls", "public with sharing class TerritorioService {}\n")
        self.write(f"{base}/TerritorioServiceTest.cls", "@IsTest private class TerritorioServiceTest {}\n")
        for role in ("apex-developer", "security-admin", "test-engineer"):
            self.report(fid, role)

    def to_verify(self) -> str:
        fid = self.to_build()
        self.build_apex(fid)
        rc, out = self.hx("advance", fid)
        assert rc == 0, out
        return fid

    def review_all(self, fid: str, roles: Optional[List[str]] = None) -> None:
        roles = roles or ["qa-verifier", "code-reviewer", "security-reviewer", "performance-reviewer"]
        acs = " ".join(ac["id"] for ac in self.feature(fid)["acceptance_criteria"])
        self.write(f"docs/specs/{fid}/acceptance.md", f"# Aceptación\n\n## Trazabilidad\n{acs} | PASS |\n")
        for role in roles:
            self.report(fid, role, "review")
            rc, out = self.hx("verdict", role, "pass", "--note", "ok")
            assert rc == 0, out

    def to_release(self) -> str:
        fid = self.to_verify()
        assert self.hx("gate", "run", "all")[0] == 0
        self.review_all(fid)
        rc, out = self.hx("advance", fid)
        assert rc == 0, out
        return fid
