"""Selección de tests Apex por feature: solo los que cubren lo que cambia, no los centenares del repo."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
TEST_SRC = "@isTest\nprivate class {n} {{\n  @isTest static void t() {{ {body} }}\n}}\n"
PROD_SRC = "public with sharing class {n} {{ public static Boolean ok() {{ return true; }} }}\n"


class SfutilCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cls = self.root / "force-app" / "main" / "default" / "classes"
        self.cls.mkdir(parents=True)

    def add(self, name, src):
        (self.cls / f"{name}.cls").write_text(src, encoding="utf-8")

    def run_util(self, *args):
        r = subprocess.run([sys.executable, str(LIB / "sfutil.py"), *args], cwd=self.root,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def changed(self, *files):
        p = self.root / "changed.txt"
        p.write_text("\n".join(files) + "\n", encoding="utf-8")
        return str(p)

    def test_solo_los_tests_de_la_feature_y_no_los_del_repo(self):
        self.add("EmailDomainUtils", PROD_SRC.format(n="EmailDomainUtils"))
        self.add("EmailDomainUtilsTest", TEST_SRC.format(n="EmailDomainUtilsTest", body="EmailDomainUtils.ok();"))
        for i in range(30):  # ruido: tests de otras clases del repo
            self.add(f"Otra{i}", PROD_SRC.format(n=f"Otra{i}"))
            self.add(f"Otra{i}Test", TEST_SRC.format(n=f"Otra{i}Test", body=f"Otra{i}.ok();"))
        ch = self.changed("force-app/main/default/classes/EmailDomainUtils.cls",
                          "force-app/main/default/classes/EmailDomainUtilsTest.cls", "docs/specs/F-001/design.md")
        self.assertEqual(self.run_util("test-classes", "--changed", ch, "force-app"), ["EmailDomainUtilsTest"])
        self.assertEqual(self.run_util("changed-apex", ch), ["EmailDomainUtils", "EmailDomainUtilsTest"])

    def test_convencion_de_nombre_y_referencia(self):
        self.add("Svc", PROD_SRC.format(n="Svc"))
        self.add("Svc_Test", TEST_SRC.format(n="Svc_Test", body="System.assert(true);"))      # por nombre
        self.add("OtroTest", TEST_SRC.format(n="OtroTest", body="Svc.ok();"))                  # por referencia
        self.add("AjenoTest", TEST_SRC.format(n="AjenoTest", body="System.assert(true);"))     # no aplica
        ch = self.changed("force-app/main/default/classes/Svc.cls")
        self.assertEqual(self.run_util("test-classes", "--changed", ch, "force-app"), ["OtroTest", "Svc_Test"])

    def test_sin_cambios_apex_no_selecciona_nada(self):
        self.add("Svc", PROD_SRC.format(n="Svc"))
        self.add("SvcTest", TEST_SRC.format(n="SvcTest", body="Svc.ok();"))
        ch = self.changed("docs/specs/F-001/design.md", "force-app/main/default/flows/X.flow-meta.xml")
        self.assertEqual(self.run_util("changed-apex", ch), [])
        self.assertEqual(self.run_util("test-classes", "--changed", ch, "force-app"), [])

    def test_clase_sin_tests_devuelve_vacio(self):
        self.add("Huerfana", PROD_SRC.format(n="Huerfana"))
        ch = self.changed("force-app/main/default/classes/Huerfana.cls")
        self.assertEqual(self.run_util("changed-apex", ch), ["Huerfana"])
        self.assertEqual(self.run_util("test-classes", "--changed", ch, "force-app"), [])

    def test_rutas_con_backslash_de_windows(self):
        self.add("Svc", PROD_SRC.format(n="Svc"))
        self.add("SvcTest", TEST_SRC.format(n="SvcTest", body="Svc.ok();"))
        ch = self.changed("force-app\\main\\default\\classes\\Svc.cls")
        self.assertEqual(self.run_util("test-classes", "--changed", ch, "force-app"), ["SvcTest"])

    def test_sin_flag_changed_lista_todos_como_antes(self):
        self.add("Svc", PROD_SRC.format(n="Svc"))
        self.add("SvcTest", TEST_SRC.format(n="SvcTest", body="Svc.ok();"))
        self.assertEqual(self.run_util("test-classes", "force-app"), ["SvcTest"])


if __name__ == "__main__":
    unittest.main()
