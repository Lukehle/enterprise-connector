import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from work_context import core
from work_context.cli import main
from work_context.common import atomic_json, read_json, utc_now


class SharedCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        code, result = self.run_cli("init-shared", "--shared-vault", str(self.root / "Google Drive Vault"),
            "--local-workspace", str(self.root / "Luke Workspace"), "--state-dir", str(self.root / "Luke State"), "--demo")
        self.assertEqual(code, 0, result)
        self.config = result["config_path"]
        self.c = core.load_config(Path(self.config))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, json.loads(out.getvalue() or err.getvalue())

    def cmd(self, *args):
        return self.run_cli("--config", self.config, *args)

    def reviewed(self):
        code, fresh = self.cmd("refresh")
        self.assertEqual(code, 0, fresh)
        self.assertEqual(self.cmd("approve-source", "--reviewed-hash", fresh["source_hash"], "--actor", "Synthetic Reviewer")[0], 0)
        code, published = self.cmd("refresh")
        self.assertEqual(code, 0, published)
        return published

    def test_refresh_publishes_reviewed_context_and_reader_can_validate(self):
        self.reviewed()
        code, reader = self.run_cli("init-shared", "--shared-vault", str(self.root / "Google Drive Vault"),
            "--local-workspace", str(self.root / "Boss Workspace"), "--state-dir", str(self.root / "Boss State"), "--member-id", "boss")
        self.assertEqual(code, 0, reader)
        code, shared = self.run_cli("--config", reader["config_path"], "shared-status")
        self.assertEqual(code, 0, shared)
        self.assertEqual(shared["state"], "FRESH")
        self.assertNotEqual(reader["config_path"], self.config)
        code, rejected = self.run_cli("--config", reader["config_path"], "shared-publish")
        self.assertEqual(code, 2)
        self.assertEqual(rejected["error"]["code"], "SHARED_PUBLISHER")

    def test_changed_notion_content_waits_for_review_and_removes_shared_current(self):
        self.reviewed()
        pages = read_json(Path(self.c["fixture_path"]))
        pages[0]["markdown"] += "\nA changed business statement.\n"
        atomic_json(Path(self.c["fixture_path"]), pages)
        code, changed = self.cmd("refresh")
        self.assertEqual(code, 0, changed)
        self.assertEqual(changed["review_status"], "REVIEW_REQUIRED")
        self.assertEqual(self.cmd("shared-status")[1]["state"], "UNAVAILABLE")

    def test_direct_scope_change_invalidates_shared_projection(self):
        self.reviewed()
        code, configured = self.cmd("configure-notion", "--page-id", "00000000-0000-4000-8000-000000000001", "--reviewed-scope")
        self.assertEqual(code, 0, configured)
        self.assertEqual(self.cmd("shared-status")[1]["state"], "UNAVAILABLE")

    def test_revoked_source_review_invalidates_shared_projection_on_status(self):
        self.reviewed()
        atomic_json(core.state_path(self.c, "source_review.json"), {"revoked": True})
        self.assertEqual(self.cmd("status")[1]["state"], "STALE")
        self.assertEqual(self.cmd("shared-status")[1]["state"], "UNAVAILABLE")

    def test_schedule_apply_exports_only_local_artifact_and_requires_exact_hash(self):
        code, plan = self.cmd("refresh-schedule")
        self.assertEqual(code, 0, plan)
        self.assertFalse(Path(plan["output_path"]).exists())
        self.assertEqual(self.cmd("refresh-schedule", "--apply", "--reviewed-hash", "wrong")[0], 2)
        code, exported = self.cmd("refresh-schedule", "--apply", "--reviewed-hash", plan["reviewed_operation_hash"])
        self.assertEqual(code, 0, exported)
        self.assertFalse(exported["installed"])
        self.assertTrue(Path(exported["plist_path"]).is_relative_to(self.root / "Luke State"))

    def test_unverified_model_template_cannot_start_routing(self):
        self.reviewed()
        code, profile = self.run_cli("route-template", "--workflow", "claude")
        self.assertEqual(code, 0, profile)
        path = self.root / "reference-models.json"
        atomic_json(path, profile)
        code, result = self.cmd("route-init", "--workflow", "claude", "--models", str(path))
        self.assertEqual(code, 2, result)
        self.assertEqual(result["error"]["code"], "ROUTE_CONFIG")

    def test_cli_selects_sonnet_only_after_two_failed_haiku_candidates(self):
        self.reviewed()
        code, profile = self.run_cli("route-template", "--workflow", "claude")
        self.assertEqual(code, 0)
        for value in profile.values():
            value["verified_at"] = utc_now()
            value["verification_note"] = "Synthetic test fixture; no account or model call."
        profile_path = self.root / "models.json"
        atomic_json(profile_path, profile)
        code, run = self.cmd("route-init", "--workflow", "claude", "--models", str(profile_path))
        self.assertEqual(code, 0, run)
        report = self.root / "report.md"
        report.write_text("Synthetic outcome fixture. No model or project test was run.", encoding="utf-8")
        for expected_stage, model, outcome in (("PLAN", "claude-opus-4-8", "plan-approved"),
                ("BUILD", "claude-haiku-4-5-20251001", "build-failed"),
                ("BUILD", "claude-haiku-4-5-20251001", "build-failed"),
                ("RECOVERY", "claude-sonnet-5", "build-passed"),
                ("REVIEW", "claude-opus-4-8", "review-passed"),
                ("ACCEPTANCE", "human", "accepted")):
            code, stage = self.cmd("route-next", "--run-id", run["run_id"])
            self.assertEqual(code, 0, stage)
            self.assertEqual(stage["stage"], expected_stage)
            self.assertEqual(stage["model_id"], model)
            evidence = {**stage["evidence_template"], "outcome": outcome,
                        "summary": "Synthetic test fixture.", "report_path": str(report)}
            evidence_path = self.root / "evidence.json"
            atomic_json(evidence_path, evidence)
            code, recorded = self.cmd("route-record", "--run-id", run["run_id"], "--outcome", outcome,
                "--evidence", str(evidence_path), "--actor", "Synthetic reviewer")
            self.assertEqual(code, 0, recorded)
        self.assertEqual(self.cmd("route-next", "--run-id", run["run_id"])[1]["stage"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
