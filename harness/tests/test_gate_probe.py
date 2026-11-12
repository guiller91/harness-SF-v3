"""La sonda del plugin en el gate static no debe fallar por SIGPIPE (set -o pipefail + grep -q)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "gates" / "static.sh"
LIB = Path(__file__).resolve().parents[1] / "lib"


@unittest.skipUnless(shutil.which("bash"), "requiere bash")
class GateProbeCase(unittest.TestCase):
    def test_detecta_el_plugin_aunque_sf_imprima_mucho_despues(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            sf = tmp / "bin" / "sf"
            # el plugin sale pronto y luego mucha salida: con pipefail + grep -q, sf recibía SIGPIPE
            sf.write_text('#!/bin/sh\nif [ "$1" = plugins ]; then\n  echo "agent 2.3.0"; echo "code-analyzer 5.16.0"\n'
                          '  i=0; while [ $i -lt 20000 ]; do echo "linea de relleno larga para llenar el buffer $i"; '
                          'i=$((i+1)); done\n  exit 0\nfi\nexit 1\n')
            sf.chmod(0o755)
            ev = tmp / "ev"
            ev.mkdir()
            env = dict(os.environ, PATH=f"{tmp / 'bin'}:{os.environ['PATH']}", HX_ROOT=str(tmp),
                       HX_SUMMARY_FILE=str(ev / "summary"), HX_EVIDENCE_DIR=str(ev), HX_CHANGED_FILES=str(ev / "c.txt"),
                       HX_PY=shutil.which("python3"), HX_LIB=str(LIB), HX_PKG_DIRS="force-app", HX_SEVERITY="3",
                       HX_RULE_SELECTORS="Recommended", HX_ANALYZER_CONFIG="", HX_ANALYZER_SCOPE="changed")
            r = subprocess.run(["bash", str(GATE)], cwd=tmp, env=env, capture_output=True, text=True)
            self.assertNotIn("no accesible", r.stdout + r.stderr)
            self.assertIn("Verificando Code Analyzer", r.stdout)


if __name__ == "__main__":
    unittest.main()
