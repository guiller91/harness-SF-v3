"""`./hx watch`: servidor local de solo lectura que alimenta el visor animado."""
import re
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from harness.tests.util import Project


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.proc = subprocess.Popen([sys.executable, str(self.p.root / "harness/cli.py"), "watch", "--port", "0",
                                      "--no-open"], cwd=self.p.root, env=self.p.env(), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
        line = self.proc.stdout.readline()
        m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
        self.assertIsNotNone(m, line)
        self.url = f"http://127.0.0.1:{m.group(1)}"

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.p.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.url + path, timeout=10)

    def test_sirve_el_visor_y_el_log_de_eventos(self):
        page = self.get("/")
        self.assertIn("text/html", page.headers["Content-Type"])
        self.assertIn("Harness en acción", page.read().decode("utf-8"))
        self.assertEqual(self.get("/events.jsonl").read(), b"")          # sin eventos aún
        (self.p.root / ".harness").mkdir(exist_ok=True)
        (self.p.root / ".harness/events.jsonl").write_text('{"at":"2026-11-13T08:00:00Z","event":"propose"}\n',
                                                           encoding="utf-8")
        r = self.get("/events.jsonl")
        self.assertIn("text/plain", r.headers["Content-Type"])
        self.assertIn('"propose"', r.read().decode("utf-8"))
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_solo_lectura_y_solo_dos_rutas(self):
        for path in ("/harness.config.json", "/../feature_list.json", "/.harness/events.jsonl", "/etc/passwd"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get(path)
            self.assertEqual(ctx.exception.code, 404, path)
        req = urllib.request.Request(self.url + "/", data=b"x", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertIn(ctx.exception.code, (501, 405))


class WatchGuardTest(unittest.TestCase):
    def test_un_agente_no_lanza_el_servidor(self):
        p = Project()
        try:
            rc, out, err = p.hook("guard_bash.py", {"tool_name": "Bash", "agent_type": "apex-developer",
                                                    "tool_input": {"command": "./hx watch"}})
            self.assertEqual(rc, 2)
            self.assertIn("hx-role", err)
        finally:
            p.cleanup()


class EventosParaElVisorTest(unittest.TestCase):
    def test_gate_start_y_edit_quedan_registrados(self):
        import json
        p = Project()
        try:
            fid = p.to_verify()
            self.assertEqual(p.hx("gate", "run", "static")[0], 0)
            p.hook("post_edit_checks.py", {"tool_name": "Write", "agent_type": "apex-developer",
                                           "tool_input": {"file_path": str(p.root / "force-app/main/default/classes/TerritorioService.cls")}})
            evs = [json.loads(x) for x in (p.root / ".harness/events.jsonl").read_text(encoding="utf-8").splitlines()]
            kinds = [e["event"] for e in evs]
            self.assertLess(kinds.index("gate_start"), kinds.index("gate"))
            edit = next(e for e in evs if e["event"] == "edit")
            self.assertEqual(edit["role"], "apex-developer")
            self.assertTrue(edit["file"].endswith("TerritorioService.cls"))
            self.assertNotIn("content", edit)           # nunca el contenido, solo la ruta
            self.assertEqual(fid, edit.get("feature"))
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
