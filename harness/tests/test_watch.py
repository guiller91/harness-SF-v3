"""`./hx watch`: centro de control local (visor, acciones humanas y orquestador headless)."""
import json
import os
import re
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from harness.tests.util import Project


FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_claude.py"


def start(p, *extra, path_prefix=None):
    env = p.env()
    if path_prefix:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    proc = subprocess.Popen([sys.executable, str(p.root / "harness/cli.py"), "watch", "--port", "0", "--no-open",
                             *extra], cwd=p.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    line = proc.stdout.readline()
    m = re.search(r"http://127\.0\.0\.1:(\d+)/(?:\?k=([\w-]+))?", line)
    assert m, line
    return proc, f"http://127.0.0.1:{m.group(1)}", m.group(2)


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        bindir = Path(self.p.tmp) / "bin"
        bindir.mkdir()
        fake = bindir / "claude"
        fake.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n", encoding="utf-8")
        fake.chmod(0o755)
        self.proc, self.url, self.token = start(self.p, path_prefix=str(bindir))

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.p.cleanup()

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.url + path, headers=headers or {}), timeout=10)

    def api(self, path, body=None, token=None, headers=None):
        h = {"X-HX-Token": self.token if token is None else token, **(headers or {})}
        data = None
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if data else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    def status(self, fn):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            fn()
        return ctx.exception.code

    def test_sirve_el_visor_y_el_log_de_eventos(self):
        page = self.get("/")
        self.assertIn("text/html", page.headers["Content-Type"])
        html = page.read().decode("utf-8")
        self.assertIn("en acción", html)
        self.assertNotIn(self.token, html)                               # la clave nunca va en el HTML
        self.assertEqual(self.get("/events.jsonl").read(), b"")
        (self.p.root / ".harness").mkdir(exist_ok=True)
        (self.p.root / ".harness/events.jsonl").write_text('{"at":"2026-11-13T08:00:00Z","event":"propose"}\n',
                                                           encoding="utf-8")
        r = self.get("/events.jsonl")
        self.assertIn('"propose"', r.read().decode("utf-8"))
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_sirve_el_robot_3d(self):
        r = self.get("/assets/robot.glb")
        self.assertEqual(r.headers["Content-Type"], "model/gltf-binary")
        self.assertEqual(r.read(4), b"glTF")

    def test_logo_del_proyecto(self):
        self.assertEqual(self.status(lambda: self.get("/brand/logo")), 404)
        (self.p.root / ".harness/brand").mkdir(parents=True)
        (self.p.root / ".harness/brand/logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        r = self.get("/brand/logo")
        self.assertEqual(r.headers["Content-Type"], "image/png")
        self.assertTrue(r.read().startswith(b"\x89PNG"))

    def test_solo_dos_rutas_publicas(self):
        for path in ("/harness.config.json", "/../feature_list.json", "/.harness/events.jsonl", "/etc/passwd"):
            self.assertEqual(self.status(lambda: self.get(path)), 404, path)

    def test_la_api_exige_clave_host_y_origen(self):
        self.assertEqual(self.status(lambda: self.api("/api/state", token="")), 403)
        self.assertEqual(self.status(lambda: self.api("/api/state", token="x" * 32)), 403)
        self.assertEqual(self.status(lambda: self.api("/api/action", {"action": "approve", "id": "F-001"},
                                                      token="")), 403)
        self.assertEqual(self.status(lambda: self.get("/", {"Host": "evil.example:80"})), 403)   # DNS rebinding
        self.assertEqual(self.status(lambda: self.api("/api/state", headers={"Origin": "https://evil.example"})), 403)
        req = urllib.request.Request(self.url + "/api/action", data=b"action=approve", method="POST",
                                     headers={"X-HX-Token": self.token, "Content-Type": "text/plain"})
        self.assertEqual(self.status(lambda: urllib.request.urlopen(req, timeout=10)), 415)
        self.assertEqual(self.api("/api/state")["features"], [])

    def test_pedir_aprobar_y_arrancar_desde_el_panel(self):
        r = self.api("/api/action", {"action": "propose", "draft": {
            "title": "Validar dominio", "description": "Para no crear cuentas basura", "size": "S",
            "acceptance_criteria": ["rechaza dominios fuera de la lista"]}})
        self.assertEqual(r["rc"], 0, r["output"])
        st = self.api("/api/state")
        self.assertEqual(st["features"][0]["status"], "draft")
        self.assertEqual(st["pending"][0], {"action": "approve", "id": "F-001", "label": "Aprobar F-001",
                                            "kind": "feature"})
        self.assertEqual(self.api("/api/action", {"action": "approve", "id": "F-001"})["rc"], 0)
        self.assertEqual(self.api("/api/state")["pending"][0]["action"], "start")
        # La CLI sigue mandando: cerrar un borrador aprobado se rechaza igual que en la terminal.
        r = self.api("/api/action", {"action": "close", "id": "F-001"})
        self.assertNotEqual(r["rc"], 0)
        self.assertIn("release", r["output"])
        # Nada fuera de la lista blanca, ni ids raros.
        self.assertEqual(self.api("/api/action", {"action": "gate", "id": "F-001"})["rc"], 2)
        self.assertEqual(self.api("/api/action", {"action": "approve", "id": "F-001; rm -rf /"})["rc"], 2)
        self.assertEqual(self.api("/api/action", {"action": "block", "id": "F-001"})["rc"], 2)   # sin motivo
        evs = [json.loads(x) for x in (self.p.root / ".harness/events.jsonl").read_text(encoding="utf-8").splitlines()]
        acts = [(e["action"], e["rc"]) for e in evs if e["event"] == "human_action"]
        self.assertIn(("approve", 0), acts)

    def wait_idle(self):
        for _ in range(100):
            o = self.api("/api/orch?since=0")
            if not o["running"]:
                return o
            time.sleep(0.1)
        self.fail("el orquestador no terminó")

    @unittest.skipIf(os.name == "nt", "el claude falso es un script sh")
    def test_conversacion_con_el_orquestador(self):
        self.assertTrue(self.api("/api/orch?since=0")["available"])
        self.assertEqual(self.api("/api/orch/send", {"message": "Hola; & echo pwned"})["rc"], 0)
        o = self.wait_idle()
        kinds = [i["kind"] for i in o["items"]]
        self.assertEqual(kinds, ["user", "tool", "assistant", "tool-error", "done"])
        said = o["items"][2]["text"]
        self.assertIn("Recibido: Hola; & echo pwned", said)          # por stdin, intacto
        self.assertIn("resume=None", said)
        self.assertIn("prompt=True", said)
        self.assertEqual(o["items"][1]["text"], "$ ./hx status")
        self.api("/api/orch/send", {"message": "sigue"})
        o = self.wait_idle()
        self.assertIn("resume=11111111-2222-3333-4444-555555555555", o["items"][-3]["text"])
        self.assertEqual(self.api(f"/api/orch?since={o['total']}")["items"], [])
        self.assertEqual(self.api("/api/orch/reset", {})["rc"], 0)
        self.assertEqual(self.api("/api/orch?since=0")["total"], 0)


class WatchReadOnlyTest(unittest.TestCase):
    def test_solo_lectura_no_expone_la_api(self):
        p = Project()
        proc, url, token = start(p, "--read-only")
        try:
            self.assertIsNone(token)
            self.assertIn(b"Harness", urllib.request.urlopen(url + "/", timeout=10).read())
            req = urllib.request.Request(url + "/api/state", headers={"X-HX-Token": "x"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=10)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
            p.cleanup()


class WatchGuardTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()

    def tearDown(self):
        self.p.cleanup()

    def bash(self, cmd, role=None, env=None):
        ev = {"tool_name": "Bash", "tool_input": {"command": cmd}}
        if role:
            ev["agent_type"] = role
        return self.p.hook("guard_bash.py", ev, env)

    def test_nadie_salvo_el_humano_abre_el_centro_de_control(self):
        for role in (None, "apex-developer"):
            rc, _, err = self.bash("./hx watch", role)
            self.assertEqual(rc, 2)
            self.assertIn("hx-human", err)

    def test_los_agentes_no_llaman_a_la_api(self):
        for cmd in ("curl -s -X POST http://127.0.0.1:8765/api/action -d '{}'",
                    "python3 - <<'EOF'\nimport urllib.request\nurllib.request.urlopen('http://localhost:8765/api/state')\nEOF"):
            rc, _, err = self.bash(cmd)
            self.assertEqual(rc, 2, cmd)
            self.assertIn("console-api", err)

    def test_alias_protegido_con_espacios_bloquea(self):
        cfg = self.p.root / "harness.config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["org"]["protectedAliases"] = ["LEVEL - Prod"]
        cfg.write_text(json.dumps(data), encoding="utf-8")
        rc, _, err = self.bash('sf data query -q "SELECT Id FROM Account" --target-org "LEVEL - Prod"')
        self.assertEqual(rc, 2)
        self.assertIn("protected-org", err)

    def test_en_el_centro_de_control_el_orquestador_no_aprueba(self):
        rc, out, err = self.bash("./hx approve F-001", env={"HX_CONSOLE": "1"})
        self.assertEqual(rc, 2)
        self.assertIn("panel", err)
        rc, out, _ = self.bash("./hx approve F-001")          # en la terminal sigue siendo una pregunta
        self.assertEqual(rc, 0)
        self.assertIn('"ask"', out)


class EventosParaElVisorTest(unittest.TestCase):
    def test_gate_start_y_edit_quedan_registrados(self):
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
