"""El lanzador de hooks (.claude/hooks/run): encuentra Python y, si no hay, falla CERRADO en las guardas."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / ".claude" / "hooks" / "run"


def sandbox_path(tmp: Path, tools=("sh", "dirname", "whoami", "cat")) -> str:
    """PATH con solo utilidades básicas (sin Python)."""
    bindir = tmp / "bin"
    bindir.mkdir()
    for t in tools:
        src = shutil.which(t)
        if src:
            (bindir / t).symlink_to(src)
    return str(bindir)


@unittest.skipUnless(shutil.which("sh"), "requiere sh")
class LauncherCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-launcher-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_launcher(self, script, path, hooks_dir=None, stdin=""):
        env = {"PATH": path, "HOME": str(self.tmp)}
        return subprocess.run(["sh", str(RUN), script], input=stdin, capture_output=True, text=True, env=env)

    def test_es_ejecutable(self):
        self.assertTrue(os.stat(RUN).st_mode & stat.S_IXUSR)

    def test_sin_python_las_guardas_fallan_cerrado(self):
        for g in ("guard_bash.py", "guard_write.py"):
            r = self.run_launcher(g, self._nopy())
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("Python", r.stderr)

    def test_sin_python_el_resto_no_tumba_la_sesion(self):
        for h in ("session_context.py", "stop_guard.py", "post_edit_checks.py"):
            r = self.run_launcher(h, self._nopy())
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("omitido", r.stderr)

    def test_con_python_ejecuta_el_hook_y_pasa_stdin(self):
        hooks = self.tmp / "h"
        hooks.mkdir()
        shutil.copy(RUN, hooks / "run")
        (hooks / "eco.py").write_text("import sys\nsys.stdout.write(sys.stdin.read().upper())\n")
        r = subprocess.run(["sh", str(hooks / "run"), "eco.py"], input="hola", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, "HOLA"), r.stderr)

    def test_el_hook_imprime_unicode_aunque_la_consola_sea_cp1252(self):
        hooks = self.tmp / "u"
        hooks.mkdir()
        shutil.copy(RUN, hooks / "run")
        (hooks / "uni.py").write_text("print('cobertura \u2265 85 % \u2192 ok')\n")
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        r = subprocess.run(["sh", str(hooks / "run"), "uni.py"], capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("\u2265".encode("utf-8"), r.stdout)

    def test_el_stub_de_la_store_no_cuenta_como_python(self):
        """Simula `python3` de WindowsApps: imprime un aviso y falla. Debe descartarse."""
        path = self._nopy()
        stub = Path(path) / "python3"
        stub.write_text("#!/bin/sh\necho 'no se encontro Python; ejecutar sin argumentos para instalar' >&2\nexit 9009\n")
        stub.chmod(0o755)
        r = self.run_launcher("guard_bash.py", path)
        self.assertEqual(r.returncode, 2, r.stderr)

    def _nopy(self):
        d = self.tmp / f"np{len(list(self.tmp.iterdir()))}"
        d.mkdir()
        return sandbox_path(d)


if __name__ == "__main__":
    unittest.main()
