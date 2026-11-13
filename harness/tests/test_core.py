import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import core  # noqa: E402

PIPELINE = core.read_json(Path(__file__).resolve().parents[1] / "pipeline.json")


class GlobTest(unittest.TestCase):
    def test_double_star_matches_any_depth(self):
        self.assertTrue(core.glob_match("force-app/main/default/classes/A.cls", "force-app/**/classes/**"))
        self.assertTrue(core.glob_match("force-app/classes/A.cls", "force-app/**/classes/**"))
        self.assertFalse(core.glob_match("src/classes/A.cls", "force-app/**/classes/**"))

    def test_single_star_stays_in_segment(self):
        self.assertTrue(core.glob_match("a/b.cls", "a/*.cls"))
        self.assertFalse(core.glob_match("a/x/b.cls", "a/*.cls"))

    def test_negation_excludes(self):
        pats = ["force-app/**/classes/**", "!force-app/**/classes/*Test.cls"]
        self.assertTrue(core.match_any("force-app/main/default/classes/A.cls", pats))
        self.assertFalse(core.match_any("force-app/main/default/classes/ATest.cls", pats))

    def test_rel_rejects_paths_outside_project(self):
        base = Path("/tmp/proj")
        self.assertEqual(core.rel("/tmp/proj/force-app/a.cls", base), "force-app/a.cls")
        self.assertEqual(core.rel("force-app/../force-app/a.cls", base), "force-app/a.cls")
        self.assertIsNone(core.rel("/tmp/other/a.cls", base))
        self.assertIsNone(core.rel("../x", base))


class ClassifyTest(unittest.TestCase):
    CASES = {
        "force-app/main/default/classes/PedidoService.cls": "apex",
        "force-app/main/default/classes/PedidoServiceTest.cls": "apex-test",
        "force-app/main/default/classes/TestDataFactory.cls-meta.xml": "apex-test",
        "force-app/main/default/triggers/Pedido.trigger": "apex",
        "force-app/main/default/lwc/lista/lista.js": "lwc",
        "force-app/main/default/lwc/lista/__tests__/lista.test.js": "lwc-test",
        "force-app/main/default/flows/Case_AfterSave.flow-meta.xml": "flow",
        "force-app/main/default/objects/Pedido__c/fields/Estado__c.field-meta.xml": "data-model",
        "force-app/main/default/objects/Aviso__e/Aviso__e.object-meta.xml": "integration",
        "force-app/main/default/permissionsets/Pedidos.permissionset-meta.xml": "permissions",
        "force-app/main/default/namedCredentials/ERP.namedCredential-meta.xml": "integration",
        "force-app/main/default/aiAuthoringBundles/Soporte/Soporte.agent": "agentforce",
        "force-app/main/default/flexipages/Pedido.flexipage-meta.xml": "ui-config",
        "force-app/main/default/unknownType/x.xml": "other",
    }

    def test_classification(self):
        for path, kind in self.CASES.items():
            self.assertEqual(core.classify(path), kind, path)


class PlanTest(unittest.TestCase):
    def test_apex_change_requires_tests_security_and_performance(self):
        plan = core.derive_plan({"apex"}, "M", PIPELINE)
        self.assertEqual(plan["build"], ["apex-developer", "security-admin", "test-engineer"])
        self.assertEqual(plan["gates"], ["format", "secrets", "static", "apex-tests"])
        self.assertEqual(plan["reviews"], ["qa-verifier", "code-reviewer", "security-reviewer", "performance-reviewer"])
        self.assertEqual(plan["release"], ["release-manager", "docs-writer"])
        self.assertEqual(plan["release_gates"], ["deploy-validate", "regression"])

    def test_size_s_is_lighter_but_keeps_security(self):
        plan = core.derive_plan({"apex"}, "S", PIPELINE)
        self.assertEqual(plan["reviews"], ["qa-verifier", "code-reviewer", "security-reviewer"])
        self.assertEqual(plan["release"], ["release-manager"])
        self.assertEqual(plan["release_gates"], ["deploy-validate"])
        self.assertIn("secrets", plan["gates"])

    def test_lwc_adds_accessibility_and_jest(self):
        plan = core.derive_plan({"lwc"}, "M", PIPELINE)
        self.assertIn("accessibility-reviewer", plan["reviews"])
        self.assertIn("lwc-tests", plan["gates"])
        self.assertNotIn("apex-tests", plan["gates"])

    def test_small_feature_skips_analysts(self):
        self.assertEqual(core.derive_plan({"apex"}, "S", PIPELINE)["design"], ["solution-architect"])
        self.assertEqual(core.derive_plan({"apex"}, "L", PIPELINE)["design"],
                         ["business-analyst", "org-analyst", "solution-architect"])

    def test_build_order_is_canonical(self):
        plan = core.derive_plan({"lwc", "apex", "data-model", "flow", "permissions"}, "M", PIPELINE)
        self.assertEqual(plan["build"], ["data-modeler", "apex-developer", "flow-developer", "lwc-developer",
                                         "security-admin", "test-engineer"])

    def test_docs_only_change_needs_no_gates(self):
        plan = core.derive_plan(set(), "S", PIPELINE)
        self.assertEqual(plan["gates"], [])
        self.assertEqual(plan["reviews"], ["qa-verifier"])


if __name__ == "__main__":
    unittest.main()
