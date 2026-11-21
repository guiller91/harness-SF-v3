"""Centro de control: configuración (entornos, políticas, agentes), orgs, informe de evidencia y métricas."""
import json
import os
import sys
import time
import unittest
from pathlib import Path

from harness.tests.test_watch import FAKE, start
from harness.tests.util import Project
import urllib.request

FAKE_SF = Path(__file__).resolve().parent / "fixtures" / "fake_sf.py"


@unittest.skipIf(os.name == "nt", "los binarios falsos son scripts sh")
class SettingsApiTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        bindir = Path(self.p.tmp) / "bin"
        bindir.mkdir()
        for name, target in (("claude", FAKE), ("sf", FAKE_SF)):
            f = bindir / name
            f.write_text(f"#!/bin/sh\nexec {sys.executable} {target} \"$@\"\n", encoding="utf-8")
            f.chmod(0o755)
        self.proc, self.url, self.token = start(self.p, path_prefix=str(bindir))

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.p.cleanup()

    def api(self, path, body=None):
        h = {"X-HX-Token": self.token}
        data = None
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if data else "GET")
        raw = urllib.request.urlopen(req, timeout=60).read()
        return raw if path.startswith("/api/report") else json.loads(raw)

    def cfg(self):
        return json.loads((self.p.root / "harness.config.json").read_text(encoding="utf-8"))

    def test_lee_la_configuracion_y_los_agentes(self):
        c = self.api("/api/config")
        self.assertEqual(c["environments"]["target"], self.cfg()["org"]["targetOrgAlias"])
        names = {a["name"] for a in c["agents"]}
        self.assertIn("apex-developer", names)
        self.assertIn("orchestrator", names)
        self.assertIn("sf-apex", c["skills"])

    def test_politicas_previsualiza_guarda_y_deshace(self):
        body = {"coverage": 90, "testLevel": "RunSpecifiedTests", "severity": 2, "maxRework": 2, "designApproval": ["M", "L"]}
        before = (self.p.root / "harness.config.json").read_text(encoding="utf-8")
        prev = self.api("/api/config/policies", {**body, "preview": True})
        self.assertIn('"coverageGatePerClass": 90', prev["diff"])
        self.assertEqual((self.p.root / "harness.config.json").read_text(encoding="utf-8"), before)  # preview no escribe
        r = self.api("/api/config/policies", body)
        self.assertEqual(r["rc"], 0, r["output"])
        q = self.cfg()["quality"]
        self.assertEqual((q["coverageGatePerClass"], q["apexTestLevel"], q["analyzer"]["severityThreshold"]),
                         (90, "RunSpecifiedTests", 2))
        self.assertEqual(self.cfg()["workflow"]["designApprovalForSizes"], ["M", "L"])
        hist = self.api("/api/config")["history"]
        self.assertEqual(hist[0]["kind"], "policies")
        self.assertEqual(self.api("/api/config/undo", {"backup": hist[0]["backup"]})["rc"], 0)
        self.assertEqual(self.cfg()["quality"]["coverageGatePerClass"], json.loads(before)["quality"]["coverageGatePerClass"])

    def test_politicas_rechaza_valores_fuera_de_rango(self):
        for bad in ({"coverage": 60}, {"severity": 9}, {"maxRework": 0}, {"testLevel": "NoTestRun"}):
            body = {"coverage": 85, "testLevel": "RunLocalTests", "severity": 3, "maxRework": 3, "designApproval": [], **bad}
            self.assertEqual(self.api("/api/config/policies", body)["rc"], 2, bad)

    def test_entornos_no_deja_usar_una_org_protegida(self):
        env = {"model": "sandbox", "target": "sit", "validation": "uat", "devhub": "", "protected": ["prod", "SIT"]}
        r = self.api("/api/config/environments", env)
        self.assertEqual(r["rc"], 2)
        self.assertIn("protegidas", r["output"])
        self.assertEqual(self.api("/api/config/environments", {**env, "target": "x;rm -rf"})["rc"], 2)
        r = self.api("/api/config/environments", {**env, "protected": ["prod"]})
        self.assertEqual(r["rc"], 0, r["output"])
        org = self.cfg()["org"]
        self.assertEqual((org["model"], org["targetOrgAlias"], org["validationOrgAlias"]), ("sandbox", "sit", "uat"))

    def test_agente_se_edita_y_queda_coherente(self):
        a = next(x for x in self.api("/api/config")["agents"] if x["name"] == "apex-developer")
        body = {"name": "apex-developer", "description": "Escribe Apex: clases y triggers con sharing declarado.",
                "model": "opus", "skills": ["harness-protocol", "sf-apex"], "body": a["body"] + "\nNunca uses SOQL en bucles.\n"}
        prev = self.api("/api/config/agent", {**body, "preview": True})
        self.assertIn("+model: opus", prev["diff"])
        r = self.api("/api/config/agent", body)
        self.assertEqual(r["rc"], 0, r["output"])
        text = (self.p.root / ".claude/agents/apex-developer.md").read_text(encoding="utf-8")
        self.assertIn('description: "Escribe Apex: clases', text)          # con ": " va entre comillas
        self.assertIn("skills:\n  - harness-protocol\n  - sf-apex\n---", text)
        self.assertIn("Nunca uses SOQL en bucles.", text)
        self.assertEqual(self.p.hx("check")[0], 0)
        again = next(x for x in self.api("/api/config")["agents"] if x["name"] == "apex-developer")
        self.assertEqual(again["description"], body["description"])        # se lee sin comillas

    def test_agente_rechaza_nombres_y_contenido_malos(self):
        self.assertEqual(self.api("/api/config/agent", {"name": "../../etc/passwd", "description": "x" * 20,
                                                        "model": "opus", "body": "y" * 50})["rc"], 2)
        self.assertEqual(self.api("/api/config/agent", {"name": "apex-developer", "description": "corta",
                                                        "model": "opus", "body": "y" * 50})["rc"], 2)
        self.assertEqual(self.api("/api/config/agent", {"name": "apex-developer", "description": "x" * 20,
                                                        "model": "gpt", "body": "y" * 50})["rc"], 2)

    def test_si_el_harness_deja_de_ser_coherente_no_se_guarda(self):
        a = next(x for x in self.api("/api/config")["agents"] if x["name"] == "apex-developer")
        before = (self.p.root / ".claude/agents/apex-developer.md").read_text(encoding="utf-8")
        (self.p.root / ".claude/skills/sf-apex/SKILL.md").unlink()       # la skill deja de existir
        r = self.api("/api/config/agent", {"name": "apex-developer", "description": a["description"] + " (v2)",
                                           "model": a["model"], "skills": a["skills"], "body": a["body"]})
        self.assertEqual(r["rc"], 2)
        self.assertEqual((self.p.root / ".claude/agents/apex-developer.md").read_text(encoding="utf-8"), before)

    def test_orgs_y_login_web(self):
        orgs = self.api("/api/orgs")["orgs"]
        kinds = {o["alias"]: o["kind"] for o in orgs}
        self.assertEqual(kinds, {"sit": "sandbox", "prod": "production", "harness-dev": "scratch"})
        self.assertEqual(self.api("/api/orgs/login", {"alias": "bad alias", "kind": "sandbox"})["rc"], 2)
        self.assertEqual(self.api("/api/orgs/login", {"alias": "x", "kind": "mydomain", "url": "https://evil.com"})["rc"], 2)
        r = self.api("/api/orgs/login", {"alias": "acme-prod", "kind": "production"})
        self.assertEqual(r["rc"], 0, r["output"])
        for _ in range(100):
            job = self.api(f"/api/orgs/login?job={r['job']}")
            if job["state"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(job["state"], "done", job)
        self.assertIn("acme-prod", self.cfg()["org"]["protectedAliases"])   # producción: protegida al conectar

    def test_informe_y_metricas(self):
        fid = self.p.to_verify()
        self.p.hx("gate", "run", "static")
        html = self.api(f"/api/report?id={fid}").decode("utf-8")
        self.assertIn("Informe de evidencia", html)
        self.assertIn("Análisis estático", html)
        self.assertNotIn("progress/current.md", html)
        core_events = self.p.root / ".harness/events.jsonl"
        with open(core_events, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": "2026-11-21T10:00:00Z", "event": "console_run", "feature": fid,
                                 "cost_usd": 0.42, "duration_s": 30, "turns": 5}) + "\n")
        m = self.api("/api/metrics")
        row = next(r for r in m["features"] if r["id"] == fid)
        self.assertAlmostEqual(row["cost"]["usd"], 0.42)


class ReportCliTest(unittest.TestCase):
    def test_hx_report_escribe_el_informe(self):
        p = Project()
        try:
            fid = p.to_verify()
            rc, out = p.hx("report", fid)
            self.assertEqual(rc, 0, out)
            self.assertTrue((p.root / "docs/specs" / fid / "evidence.html").is_file())
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
