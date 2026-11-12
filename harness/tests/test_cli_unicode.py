"""La CLI no debe morir imprimiendo símbolos no cp1252 (≥, →, ✓) en una consola de Windows."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class CliUnicodeCase(unittest.TestCase):
    def test_force_utf8_evita_unicodeencodeerror(self):
        code = ("import sys; sys.path.insert(0, 'harness'); import cli; cli._force_utf8(); "
                "print('criterio \u2265 85 \u2192 \u2713')")
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIn("\u2265".encode("utf-8"), r.stdout)

    def test_sin_el_arreglo_falla_en_cp1252(self):
        """Control: demuestra que el entorno reproduce el bug de Windows."""
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        r = subprocess.run([sys.executable, "-c", "print('\u2265')"], capture_output=True, env=env)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
