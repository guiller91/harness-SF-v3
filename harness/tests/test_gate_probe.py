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

    def test_lista_de_cambiados_con_crlf_se_analiza(self):
        """En Windows la lista puede traer CRLF: no debe dar 'sin ficheros que analizar'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            (tmp / "force-app" / "classes").mkdir(parents=True)
            (tmp / "force-app" / "classes" / "A.cls").write_text("public class A {}")
            sf = tmp / "bin" / "sf"
            sf.write_text('#!/bin/sh\nif [ "$1" = plugins ]; then echo "code-analyzer 5.16.0"; exit 0; fi\n'
                          'echo "SF_CALLED $*"; exit 0\n')
            sf.chmod(0o755)
            ev = tmp / "ev"
            ev.mkdir()
            (ev / "c.txt").write_bytes(b"force-app/classes/A.cls\r\n")
            env = dict(os.environ, PATH=f"{tmp / 'bin'}:{os.environ['PATH']}", HX_ROOT=str(tmp),
                       HX_SUMMARY_FILE=str(ev / "summary"), HX_EVIDENCE_DIR=str(ev), HX_CHANGED_FILES=str(ev / "c.txt"),
                       HX_PY=shutil.which("python3"), HX_LIB=str(LIB), HX_PKG_DIRS="force-app", HX_SEVERITY="3",
                       HX_RULE_SELECTORS="Recommended", HX_ANALYZER_CONFIG="", HX_ANALYZER_SCOPE="changed")
            r = subprocess.run(["bash", str(GATE)], cwd=tmp, env=env, capture_output=True, text=True)
            self.assertNotIn("No hay ficheros", r.stdout)
            self.assertIn("--target force-app/classes/A.cls", r.stdout)

    def test_prefiere_sf_que_no_pasa_por_sf_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for d in ("a", "b"):
                (tmp / d).mkdir()
            bad, good = tmp / "a" / "sf", tmp / "b" / "sf"
            bad.write_text('#!/bin/sh\n"$(dirname "$0")/../client/bin/sf.cmd" "$@"\n')
            good.write_text('#!/bin/sh\necho BUENO "$@"\n')
            for f in (bad, good):
                f.chmod(0o755)
            ev = tmp / "ev"
            ev.mkdir()
            (ev / "c.txt").write_text("")
            script = tmp / "g.sh"
            script.write_text('source "%s/gates/_lib.sh"\nsf --version\n' % LIB.parent)
            env = dict(os.environ, PATH=f"{tmp / 'a'}:{tmp / 'b'}:{os.environ['PATH']}", HX_ROOT=str(tmp),
                       HX_SUMMARY_FILE=str(ev / "s"), HX_CHANGED_FILES=str(ev / "c.txt"))
            r = subprocess.run(["bash", str(script)], cwd=tmp, env=env, capture_output=True, text=True)
            self.assertIn("BUENO --version", r.stdout)


if __name__ == "__main__":
    unittest.main()
