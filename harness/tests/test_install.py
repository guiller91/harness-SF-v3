"""install.sh: instala y actualiza sin pisar lo que es del proyecto (agentes personalizados, hooks, config)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "necesita bash")
class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-install-"))
        self.dest = self.tmp / "proj"
        self.dest.mkdir()
        (self.dest / "sfdx-project.json").write_text('{"packageDirectories":[{"path":"force-app","default":true}]}')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self, *extra):
        proc = subprocess.run(["bash", str(SRC / "install.sh"), str(self.dest), *extra], capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def test_actualizar_conserva_agentes_personalizados_y_anade_hooks_nuevos(self):
        self.install()
        agent = self.dest / ".claude/agents/apex-developer.md"
        other = self.dest / ".claude/agents/flow-developer.md"
        self.assertTrue((self.dest / ".claude/agents/.installed.json").is_file())
        mine = agent.read_text(encoding="utf-8") + "\nRegla del cliente: nada de SOQL en triggers.\n"
        agent.write_text(mine, encoding="utf-8")
        # Un settings.json antiguo, sin el hook de actividad y con un ajuste propio del proyecto.
        st = json.loads((self.dest / ".claude/settings.json").read_text(encoding="utf-8"))
        st["hooks"]["PreToolUse"] = [g for g in st["hooks"]["PreToolUse"]
                                     if "activity.py" not in json.dumps(g)]
        st["env"] = {"MI_VARIABLE": "1"}
        (self.dest / ".claude/settings.json").write_text(json.dumps(st), encoding="utf-8")
        cfg = self.dest / "harness.config.json"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('"CHANGE_ME"', '"acme"'), encoding="utf-8")
        # El agente sin tocar se queda desfasado respecto al harness.
        other.write_text(other.read_text(encoding="utf-8").replace("\n---\n", "\n---\nVERSIÓN VIEJA\n", 1),
                         encoding="utf-8")
        manifest = json.loads((self.dest / ".claude/agents/.installed.json").read_text(encoding="utf-8"))
        import hashlib
        manifest["flow-developer.md"] = hashlib.sha256(other.read_bytes()).hexdigest()
        (self.dest / ".claude/agents/.installed.json").write_text(json.dumps(manifest), encoding="utf-8")

        out = self.install("--force")
        self.assertEqual(agent.read_text(encoding="utf-8"), mine)                     # lo tuyo, intacto
        self.assertTrue((self.dest / ".claude/agents/apex-developer.md.upstream").is_file())
        self.assertIn("apex-developer.md: lo personalizaste", out)
        self.assertNotIn("VERSIÓN VIEJA", other.read_text(encoding="utf-8"))           # lo no tocado, al día
        st2 = json.loads((self.dest / ".claude/settings.json").read_text(encoding="utf-8"))
        self.assertIn("activity.py", json.dumps(st2["hooks"]["PreToolUse"]))         # hook nuevo añadido
        self.assertEqual(st2["env"], {"MI_VARIABLE": "1"})                            # ajuste propio intacto
        self.assertEqual(json.dumps(st2).count("guard_bash.py"), 1)                   # sin duplicar guardas
        self.assertIn('"acme"', cfg.read_text(encoding="utf-8"))                       # config intacta
        gi = (self.dest / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".harness/console/", gi)
        self.assertIn(".claude/agents/*.upstream", gi)

    def test_settings_antiguo_con_python3_no_duplica_guardas(self):
        self.install()
        path = self.dest / ".claude/settings.json"
        text = path.read_text(encoding="utf-8")
        import re
        old = re.sub(r'sh \\"\$CLAUDE_PROJECT_DIR/\.claude/hooks/run\\" ([\w.-]+\.py)',
                     lambda m: 'python3 \\"$CLAUDE_PROJECT_DIR/.claude/hooks/' + m.group(1) + '\\"', text)
        self.assertIn("python3", old)
        json.loads(old)
        path.write_text(old, encoding="utf-8")
        self.install("--force")
        st = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(json.dumps(st).count("guard_bash.py"), 1)


if __name__ == "__main__":
    unittest.main()
