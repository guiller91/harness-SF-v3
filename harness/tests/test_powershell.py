"""La herramienta PowerShell de Claude Code (Windows) no puede saltarse las guardas de Bash."""
import json
import unittest
from pathlib import Path

from .util import Project

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))


class PowerShellCase(unittest.TestCase):
    def test_la_herramienta_esta_denegada_para_que_los_agentes_usen_bash(self):
        self.assertIn("PowerShell", SETTINGS["permissions"]["deny"])

    def test_la_guarda_de_bash_tambien_vigila_powershell(self):
        matchers = {g["matcher"] for g in SETTINGS["hooks"]["PreToolUse"]}
        guard = next(m for m in matchers if "Bash" in m)
        self.assertIn("PowerShell", guard.split("|"))

    def test_guard_bash_bloquea_una_org_no_permitida_via_powershell(self):
        p = Project()
        self.addCleanup(p.cleanup)
        ev = {"hook_event_name": "PreToolUse", "tool_name": "PowerShell", "agent_type": "apex-developer",
              "tool_input": {"command": 'sf project deploy start -d force-app -o "LEVEL - Prod"; Get-Date'}}
        code, _out, err = p.hook("guard_bash.py", ev)
        self.assertEqual(code, 2, err)


if __name__ == "__main__":
    unittest.main()
