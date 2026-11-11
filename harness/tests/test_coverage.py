"""Gate apex-tests: cobertura POR CLASE de lo que toca la feature, no la media."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"


class CoverageGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hx-cov-"))
        self.classes = self.tmp / "force-app/main/default/classes"
        self.classes.mkdir(parents=True)
        (self.tmp / "force-app/main/default/triggers").mkdir()

    def src(self, name, body, folder="classes", ext="cls"):
        path = self.tmp / f"force-app/main/default/{folder}/{name}.{ext}"
        path.write_text(body, encoding="utf-8")
        return str(path)

    def run_gate(self, result, changed, gate=85, cli_exit=0):
        res = self.tmp / "run.json"
        res.write_text(json.dumps(result) if not isinstance(result, str) else result, encoding="utf-8")
        ch = self.tmp / "changed.txt"
        ch.write_text("\n".join(changed), encoding="utf-8")
        summary = self.tmp / "summary"
        proc = subprocess.run([sys.executable, str(LIB / "coverage.py"), "--result", str(res), "--changed", str(ch),
                               "--gate", str(gate), "--summary", str(summary), "--cli-exit", str(cli_exit)],
                              capture_output=True, text=True, cwd=self.tmp)
        return proc.returncode, proc.stdout, summary.read_text(encoding="utf-8")

    @staticmethod
    def cli_json(rows, failing=0, tests=None):
        return {"status": 1 if failing else 0, "result": {
            "summary": {"outcome": "Failed" if failing else "Passed", "testsRan": 4, "passing": 4 - failing,
                        "failing": failing, "testRunCoverage": "91%"},
            "tests": tests or [],
            "coverage": {"coverage": [{"name": n, "totalLines": t, "totalCovered": c,
                                       "coveredPercent": round(100 * c / t) if t else 100} for n, t, c in rows]}}}

    def test_passes_when_every_changed_class_meets_the_gate(self):
        changed = [self.src("PedidoService", "public with sharing class PedidoService {}"),
                   self.src("PedidoServiceTest", "@IsTest private class PedidoServiceTest {}")]
        rc, out, summary = self.run_gate(self.cli_json([("PedidoService", 100, 90), ("Legacy", 100, 10)]), changed)
        self.assertEqual(rc, 0, out)
        self.assertIn("PedidoService: 90%", out)
        self.assertNotIn("Legacy", out)           # deuda ajena: no es de esta feature
        self.assertNotIn("PedidoServiceTest", out)  # las clases de test no se miden

    def test_fails_per_class_even_if_average_is_high(self):
        changed = [self.src("A", "public with sharing class A {}"), self.src("B", "public with sharing class B {}")]
        rc, out, summary = self.run_gate(self.cli_json([("A", 100, 100), ("B", 100, 84)]), changed)
        self.assertEqual(rc, 1)
        self.assertIn("B 84%", summary)
        self.assertNotIn("A 100", summary)

    def test_class_missing_from_report_counts_as_zero(self):
        changed = [self.src("SinTests", "public with sharing class SinTests { void m() {} }")]
        rc, out, summary = self.run_gate(self.cli_json([]), changed)
        self.assertEqual(rc, 1)
        self.assertIn("SinTests 0%", summary)

    def test_interfaces_enums_and_isTest_helpers_are_exempt(self):
        changed = [self.src("IPedido", "public interface IPedido { void run(); }"),
                   self.src("Estado", "public enum Estado { A, B }"),
                   self.src("TestDataFactory", "@IsTest\npublic class TestDataFactory {}"),
                   self.src("ErrorPedido", "public class ErrorPedido extends Exception {}")]
        rc, out, summary = self.run_gate(self.cli_json([("ErrorPedido", 0, 0)]), changed)
        self.assertEqual(rc, 0, out)

    def test_triggers_are_measured(self):
        changed = [self.src("PedidoTrigger", "trigger PedidoTrigger on Pedido__c (before insert) {}", "triggers", "trigger")]
        rc, out, summary = self.run_gate(self.cli_json([("PedidoTrigger", 2, 1)]), changed)
        self.assertEqual(rc, 1)
        self.assertIn("PedidoTrigger 50%", summary)

    def test_failing_test_fails_the_gate_and_is_reported(self):
        changed = [self.src("A", "public with sharing class A {}")]
        tests = [{"FullName": "ATest.bulk", "Outcome": "Fail", "Message": "Assertion Failed: esperaba 200",
                  "StackTrace": "Class.ATest.bulk: line 12"}]
        rc, out, summary = self.run_gate(self.cli_json([("A", 10, 10)], failing=1, tests=tests), changed)
        self.assertEqual(rc, 1)
        self.assertIn("ATest.bulk: Assertion Failed", out)
        self.assertIn("1 test(s) en rojo", summary)

    def test_raw_apex_node_format_is_understood(self):
        changed = [self.src("A", "public with sharing class A {}")]
        raw = {"summary": {"outcome": "Passed", "testsRan": 2, "passing": 2, "failing": 0}, "tests": [],
               "codecoverage": [{"name": "A", "numLinesCovered": 17, "numLinesUncovered": 3, "percentage": "85%"}]}
        self.assertEqual(self.run_gate(raw, changed)[0], 0)

    def test_cli_error_without_result_fails(self):
        rc, out, summary = self.run_gate({"status": 1, "name": "NoOrgFound", "message": "No authorization found"},
                                         [], cli_exit=1)
        self.assertEqual(rc, 1)
        self.assertIn("No authorization found", summary)
        self.assertEqual(self.run_gate("not json at all", [])[0], 1)

    def test_no_tests_run_is_a_failure(self):
        result = self.cli_json([])
        result["result"]["summary"].update(testsRan=0, passing=0)
        self.assertEqual(self.run_gate(result, [])[0], 1)

    def test_detects_test_classes_for_run_specified(self):
        self.src("ATest", "@IsTest\nprivate class ATest {\n  @IsTest\n  static void t() { Assert.isTrue(true); }\n}")
        self.src("TestDataFactory", "@IsTest\npublic class TestDataFactory { public static void make() {} }")
        self.src("Legacy", "public class Legacy { static testMethod void old() {} }")
        self.src("A", "public with sharing class A { /* @IsTest static void no() {} */ }")
        proc = subprocess.run([sys.executable, str(LIB / "sfutil.py"), "test-classes", "force-app"],
                              capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(proc.stdout.split(), ["ATest", "Legacy"])


if __name__ == "__main__":
    unittest.main()
