"""El escáner de secretos: detecta lo real, ignora plantillas y respeta la allowlist humana."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import secrets_scan  # noqa: E402


class SecretsCase(unittest.TestCase):
    def scan(self, rel, text, allow=None):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path(rel).parent.mkdir(parents=True, exist_ok=True)
                Path(rel).write_text(text, encoding="utf-8")
                return secrets_scan.scan([rel], allow or set())
            finally:
                os.chdir(cwd)

    def test_detecta_credenciales_reales(self):
        src = ("public class S {\n  private static final String PASSWORD_PROD = 'Sup3rS3cret!';\n"
               "  void f(){ req.setHeader('Authorization', 'Bearer abcdefghijklmnop1234'); }\n"
               "  Blob b = Blob.valueOf('admin:hunter22');\n}\n")
        found = self.scan("force-app/classes/S.cls", src)
        self.assertEqual(len(found), 3, found)
        self.assertNotIn("S3cret!", "\n".join(found))  # nunca imprime el secreto entero

    def test_ignora_plantillas_y_tests(self):
        self.assertEqual(self.scan("force-app/classes/S.cls", "String token = '{!$Credential.Password}';\n"), [])
        self.assertEqual(self.scan("force-app/classes/STest.cls", "String password = 'Sup3rS3cret!';\n"), [])

    def test_allowlist_por_huella(self):
        line = "String password = 'Sup3rS3cret!';\n"
        found = self.scan("force-app/classes/S.cls", line)
        fp = found[0].split("huella ")[1].rstrip(")")
        self.assertEqual(self.scan("force-app/classes/S.cls", line, {("force-app/classes/S.cls", fp)}), [])


if __name__ == "__main__":
    unittest.main()
