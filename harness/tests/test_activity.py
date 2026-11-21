"""Datos para la oficina del visor: qué hace cada agente, encargos e informes. Nunca secretos."""
import json
import sys
import unittest
from pathlib import Path

from harness.tests.util import Project

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude" / "hooks"))
from activity_lib import describe, describe_bash  # noqa: E402


class DescribeTest(unittest.TestCase):
    def test_comandos_se_resumen_sin_argumentos(self):
        cases = {
            "sf project deploy start -d force-app --target-org sit": ("despliega en la org", "server"),
            "SF_X=1 sf apex run test --class-names A --target-org sit": ("ejecuta tests Apex en la org", "server"),
            "sf data query -q 'SELECT Id FROM Account' --target-org sit": ("consulta datos de la org", "server"),
            "./hx gate run static": ("lanza el gate static", "desk"),
            "cd x && ./hx verdict qa-verifier pass --note 'ok'": ("firma su veredicto", "desk"),
            "npx sfdx-lwc-jest --coverage": ("ejecuta los tests de LWC", "desk"),
            "git commit -m 'feat: x'": ("git commit", "desk"),
        }
        for cmd, want in cases.items():
            self.assertEqual(describe_bash(cmd), want, cmd)

    def test_nunca_filtra_secretos(self):
        for cmd in ('curl -H "Authorization: Bearer 00Dxx!AQ8.secret" https://x.my.salesforce.com',
                    "export TOKEN=abc123 && ./deploy.sh --password hunter2",
                    "python3 -c 'print(\"sk-live-123\")'"):
            verb, _ = describe_bash(cmd)
            for bad in ("Bearer", "00Dxx", "hunter2", "abc123", "sk-live", "password"):
                self.assertNotIn(bad, verb, cmd)
        ev = describe({"tool_name": "Read", "tool_input": {"file_path": "/x/.env; rm -rf /"}})
        self.assertEqual(ev["verb"], "lee un fichero")
        ev = describe({"tool_name": "Grep", "tool_input": {"pattern": "password=.*"}})
        self.assertNotIn("password", ev["verb"])
        ev = describe({"tool_name": "WebFetch", "tool_input": {"url": "https://user:pw@developer.salesforce.com/docs?k=1"}})
        self.assertEqual(ev["verb"], "consulta developer.salesforce.com")

    def test_delegacion_con_encargo(self):
        ev = describe({"tool_name": "Task", "tool_input": {"subagent_type": "apex-developer",
                                                           "description": "Implementa EmailDomainUtils",
                                                           "prompt": "texto largo que no se registra"}})
        self.assertEqual(ev, {"kind": "delegate", "to": "apex-developer", "task": "Implementa EmailDomainUtils"})


class HooksTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def events(self, kind):
        path = self.p.root / ".harness/events.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [e for e in map(json.loads, lines) if e["event"] == kind]

    def test_activity_hook_registra_y_nunca_bloquea(self):
        fid = self.p.to_build()
        rc, out, err = self.p.hook("activity.py", {"tool_name": "Read", "agent_type": "apex-developer",
                                                   "tool_input": {"file_path": f"docs/specs/{fid}/design.md"}})
        self.assertEqual((rc, out), (0, ""))
        rc, _, _ = self.p.hook("activity.py", {"tool_name": "Task", "tool_input": {
            "subagent_type": "test-engineer", "description": "Tests de la clase"}})
        self.assertEqual(rc, 0)
        self.assertEqual(self.p.hook("activity.py", {"tool_name": "Read"})[0], 0)   # evento raro: no bloquea
        act = self.events("activity")[0]
        self.assertEqual((act["role"], act["verb"], act["feature"]), ("apex-developer", "lee design.md", fid))
        dele = self.events("delegate")[0]
        self.assertEqual((dele["role"], dele["to"], dele["task"]), ("orchestrator", "test-engineer", "Tests de la clase"))

    def test_bash_solo_se_registra_si_el_guarda_lo_deja_pasar(self):
        self.p.to_build()
        ok = {"tool_name": "Bash", "agent_type": "apex-developer",
              "tool_input": {"command": "sf project deploy start -d force-app --target-org harness-dev"}}
        bad = {"tool_name": "Bash", "agent_type": "apex-developer", "tool_input": {"command": "./hx approve F-001"}}
        self.assertEqual(self.p.hook("guard_bash.py", ok)[0], 0)
        self.assertEqual(self.p.hook("guard_bash.py", bad)[0], 2)
        acts = self.events("activity")
        self.assertEqual([(a["verb"], a["place"]) for a in acts], [("despliega en la org", "server")])

    def test_al_terminar_entrega_resumen_y_pendiente(self):
        fid = self.p.to_build()
        self.p.hook("subagent_start.py", {"agent_type": "apex-developer", "agent_id": "a1"})
        self.p.write(f"progress/{fid}/apex-developer.md",
                     "# Informe\n## Resumen\n- **EmailDomainUtils** desplegada en `sit`\n## Archivos\nx\n"
                     "## Verificación\nok\n## Pendiente\n- ¿Lista de dominios en metadata o en código?\n")
        self.assertEqual(self.p.hook("subagent_stop.py", {"agent_type": "apex-developer", "agent_id": "a1"})[0], 0)
        stop = self.events("subagent_stop")[0]
        self.assertEqual(stop["summary"], "EmailDomainUtils desplegada en sit")
        self.assertEqual(stop["pending"], "¿Lista de dominios en metadata o en código?")
        self.assertEqual(stop["report"], f"progress/{fid}/apex-developer.md")

    def test_pendiente_vacio_no_cuenta(self):
        fid = self.p.to_build()
        self.p.hook("subagent_start.py", {"agent_type": "apex-developer", "agent_id": "a1"})
        self.p.write(f"progress/{fid}/apex-developer.md",
                     "## Resumen\nHecho\n## Archivos\nx\n## Verificación\nok\n## Pendiente\nNinguno.\n")
        self.p.hook("subagent_stop.py", {"agent_type": "apex-developer", "agent_id": "a1"})
        self.assertEqual(self.events("subagent_stop")[0]["pending"], "")


if __name__ == "__main__":
    unittest.main()
