"""Máquina de estados de `./hx`: ninguna transición sin sus precondiciones."""
import json
import unittest

from .util import Project


class Base(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)


class IntakeTest(Base):
    def test_propose_validates_and_numbers_criteria(self):
        fid = self.p.propose()
        feat = self.p.feature(fid)
        self.assertEqual(fid, "F-001")
        self.assertEqual(feat["status"], "draft")
        self.assertEqual([ac["id"] for ac in feat["acceptance_criteria"]], ["AC-1", "AC-2"])

    def test_propose_rejects_draft_without_criteria(self):
        self.p.write("d.json", json.dumps({"title": "x", "description": "y"}))
        rc, out = self.p.hx("propose", "d.json")
        self.assertEqual(rc, 2)
        self.assertIn("criterio de aceptación", out)

    def test_cannot_start_without_human_approval(self):
        fid = self.p.propose()
        rc, out = self.p.hx("start", fid, "--no-branch")
        self.assertEqual(rc, 2)
        self.assertIn("approved", out)

    def test_only_one_active_feature(self):
        self.p.to_design()
        other = self.p.propose()
        self.p.hx("approve", other)
        rc, out = self.p.hx("start", other, "--no-branch")
        self.assertEqual(rc, 2)
        self.assertIn("Ya hay una feature activa", out)

    def test_start_creates_feature_branch(self):
        fid = self.p.propose()
        self.p.hx("approve", fid)
        rc, out = self.p.hx("start", fid)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.p.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "feat/F-001-asignar-territorio")


class DesignGateTest(Base):
    def test_advance_blocked_without_design_and_scope(self):
        fid = self.p.to_design()
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("design.md", out)
        self.assertIn("scope.files", out)
        self.assertEqual(self.p.feature(fid)["status"], "design")

    def test_design_must_have_required_sections(self):
        fid = self.p.to_design()
        self.p.write(f"docs/specs/{fid}/design.md", "# Diseño\n\n## Enfoque\nalgo\n")
        self.p.hx("scope", fid, "set", "force-app/**/classes/**")
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("sin secciones", out)
        self.assertIn("Mapa de archivos", out)

    def test_medium_feature_requires_analysts(self):
        fid = self.p.to_design("M")
        self.p.design_artifacts(fid, "S")  # solo el arquitecto
        self.p.hx("scope", fid, "set", "force-app/**/classes/**")
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("requirements.md", out)
        self.assertIn("org-context.md", out)

    def test_large_feature_requires_design_approval(self):
        fid = self.p.to_design("L")
        self.p.design_artifacts(fid, "L")
        self.p.hx("scope", fid, "set", "force-app/**/classes/**")
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("aprobación humana", out)
        self.assertEqual(self.p.hx("approve", fid)[0], 0)
        self.assertEqual(self.p.hx("advance", fid)[0], 0)

    def test_scope_must_point_to_product(self):
        fid = self.p.to_design()
        rc, out = self.p.hx("scope", fid, "set", "docs/**")
        self.assertEqual(rc, 2)
        self.assertIn("packageDir", out)


class BuildGateTest(Base):
    def test_advance_blocked_without_changes_or_reports(self):
        fid = self.p.to_build()
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("no hay cambios de producto", out)

    def test_out_of_scope_change_blocks(self):
        fid = self.p.to_build()
        self.p.build_apex(fid)
        self.p.write("force-app/main/default/classes/Otra.cls", "public with sharing class Otra {}\n")
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("fuera de scope", out)
        self.assertIn("Otra.cls", out)

    def test_missing_implementer_report_blocks(self):
        fid = self.p.to_build()
        self.p.build_apex(fid)
        (self.p.root / f"progress/{fid}/test-engineer.md").unlink()
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("test-engineer.md", out)

    def test_widening_scope_in_build_needs_reason(self):
        fid = self.p.to_build()
        rc, out = self.p.hx("scope", fid, "add", "force-app/**/classes/Otra*")
        self.assertEqual(rc, 2)
        self.assertIn("--reason", out)
        self.assertEqual(self.p.hx("scope", fid, "add", "force-app/**/classes/Otra*", "--reason", "helper")[0], 0)


class VerifyGateTest(Base):
    def test_advance_requires_gates_and_reviews(self):
        fid = self.p.to_verify()
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        for needle in ("gate static: missing", "gate apex-tests: missing", "review qa-verifier: missing",
                       "review security-reviewer: missing", "review performance-reviewer: missing"):
            self.assertIn(needle, out)

    def test_red_gate_blocks(self):
        fid = self.p.to_verify()
        self.p.write(".gate-fail-apex-tests", "")
        rc, out = self.p.hx("gate", "run", "all")
        self.assertEqual(rc, 1)
        self.p.review_all(fid)
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("gate apex-tests: fail", out)

    def test_evidence_goes_stale_when_source_changes(self):
        fid = self.p.to_verify()
        self.assertEqual(self.p.hx("gate", "run", "all")[0], 0)
        self.p.review_all(fid)
        self.p.write("force-app/main/default/classes/TerritorioService.cls",
                     "public with sharing class TerritorioService { /* cambio */ }\n")
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("gate static: stale", out)
        self.assertIn("review code-reviewer: stale", out)

    def test_pass_verdict_rejected_with_blockers_in_report(self):
        fid = self.p.to_verify()
        self.p.report(fid, "code-reviewer", "review", "\n- [BLOQUEANTE] `x.cls:3` — SOQL en bucle\n")
        rc, out = self.p.hx("verdict", "code-reviewer", "pass")
        self.assertEqual(rc, 2)
        self.assertIn("BLOQUEANTE", out)
        self.assertEqual(self.p.hx("verdict", "code-reviewer", "fail", "--note", "soql en bucle")[0], 0)

    def test_verdict_requires_report(self):
        self.p.to_verify()
        rc, out = self.p.hx("verdict", "security-reviewer", "pass")
        self.assertEqual(rc, 2)
        self.assertIn("falta el informe", out)

    def test_verdict_only_for_review_roles(self):
        self.p.to_verify()
        rc, out = self.p.hx("verdict", "apex-developer", "pass")
        self.assertEqual(rc, 2)

    def test_untraced_or_unverified_criteria_block(self):
        fid = self.p.to_verify()
        self.p.hx("gate", "run", "all")
        self.p.review_all(fid)
        self.p.write(f"docs/specs/{fid}/acceptance.md", "## Trazabilidad\n| AC-1 | test | gate | NO VERIFICADO |\n")
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 1)
        self.assertIn("no traza: AC-2", out)
        self.assertIn("NO VERIFICADO", out)

    def test_rework_returns_to_build_and_escalates_after_limit(self):
        fid = self.p.to_verify()
        for i in range(3):
            rc, out = self.p.hx("rework", fid, "--reason", f"fallo {i}")
            self.assertEqual(rc, 0, out)
            self.assertEqual(self.p.feature(fid)["status"], "build")
            self.assertEqual(self.p.hx("advance", fid)[0], 0)
        rc, out = self.p.hx("rework", fid, "--reason", "otra vez")
        self.assertEqual(rc, 2)
        self.assertEqual(self.p.feature(fid)["status"], "blocked")
        self.assertIn("Escala al humano", out)


class ReleaseGateTest(Base):
    def finish_release(self, fid):
        self.p.write(f"manifest/{fid}/package.xml", "<Package/>")
        self.p.write(f"docs/specs/{fid}/release.md",
                     self.p.headings(["Contenido", "Orden de despliegue", "Pasos manuales", "Rollback"]))
        self.p.report(fid, "release-manager", "release")
        self.p.report(fid, "docs-writer", "release")

    def test_close_requires_release_artifacts_and_validation(self):
        fid = self.p.to_release()
        rc, out = self.p.hx("close", fid)
        self.assertEqual(rc, 1)
        for needle in ("release.md", "package.xml", "gate deploy-validate: missing", "docs-writer.md"):
            self.assertIn(needle, out)

    def test_full_cycle_closes_and_writes_history(self):
        fid = self.p.to_release()
        self.finish_release(fid)
        self.assertEqual(self.p.hx("gate", "run", "deploy-validate")[0], 0)
        rc, out = self.p.hx("close", fid)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.p.feature(fid)["status"], "done")
        history = (self.p.root / "progress/history.md").read_text(encoding="utf-8")
        self.assertIn(f"[{fid}]", history)
        self.assertIn("gate `apex-tests`: pass", history)
        self.assertIn("TerritorioService.cls", history)
        rc, out = self.p.hx("metrics", "--json")
        data = json.loads(out)
        self.assertEqual(data["features"][0]["status"], "done")
        self.assertEqual(data["features"][0]["first_pass_gates"], 100.0)

    def test_close_refused_if_code_changed_after_verification(self):
        fid = self.p.to_release()
        self.finish_release(fid)
        self.p.hx("gate", "run", "deploy-validate")
        self.p.write("force-app/main/default/classes/TerritorioService.cls", "public with sharing class TerritorioService { Integer x; }\n")
        rc, out = self.p.hx("close", fid)
        self.assertEqual(rc, 1)
        self.assertIn("stale", out)

    def test_advance_cannot_skip_human_close(self):
        fid = self.p.to_release()
        rc, out = self.p.hx("advance", fid)
        self.assertEqual(rc, 2)
        self.assertIn("./hx close", out)


class IntegrityTest(Base):
    def test_check_passes_on_shipped_harness(self):
        rc, out = self.p.hx("check")
        self.assertEqual(rc, 0, out)

    def test_check_detects_role_without_agent(self):
        (self.p.root / ".claude/agents/qa-verifier.md").unlink()
        rc, out = self.p.hx("check")
        self.assertEqual(rc, 1)
        self.assertIn("qa-verifier", out)

    def test_status_reports_next_step(self):
        fid = self.p.to_build()
        rc, out = self.p.hx("status")
        self.assertIn("Fase: **build**", out)
        self.assertIn("delegar en `apex-developer`", out)
        self.assertTrue((self.p.root / "progress/current.md").exists())


if __name__ == "__main__":
    unittest.main()
