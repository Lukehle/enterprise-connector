import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from work_context import core, routing
from work_context.common import BridgeError, atomic_json, read_json, utc_now


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        initialized = core.initialize(self.root / "Vault", "pilot", self.root / "State", True)
        self.c = core.load_config(Path(initialized["config_path"]))
        fresh = core.sync(self.c)
        core.acknowledge_source(self.c, fresh["source_hash"], "Synthetic reviewer")
        core.sync(self.c)
        self.profile = self.models("claude")

    def models(self, workflow):
        result = routing.default_model_profile(workflow)
        for role, value in result.items():
            if not value["model_id"]:
                value["model_id"] = "account-opus-4.8"
            value.update(verified_at=utc_now(), verification_note="Synthetic test account availability attestation")
        return result

    def start(self, workflow="claude"):
        profile = self.profile if workflow == "claude" else self.models(workflow)
        return routing.initialize_route(self.c, "TASK-001", workflow, profile)["run_id"]

    def expect(self, code, function, *args, **kwargs):
        with self.assertRaises(BridgeError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def evidence(self, run_id, outcome, report="Synthetic report: examined candidate, commands and results."):
        ledger = read_json(routing._route_dir(self.c, run_id) / "ledger.json")
        if not ledger["pending"]:
            routing.next_route(self.c, run_id)
            ledger = read_json(routing._route_dir(self.c, run_id) / "ledger.json")
        current = core.status(self.c)
        payload = {"run_id": run_id, "step_id": ledger["pending"]["step_id"], "outcome": outcome, "actual_model_id": ledger["pending"]["model_id"], "code_hash": current["code_hash"], "summary": "Inspected synthetic evidence", "report_path": "report.md"}
        path = self.root / "evidence.json"
        atomic_json(path, payload)
        (self.root / "report.md").write_text(report, encoding="utf-8")
        return path

    def record(self, run_id, outcome, report="Synthetic plan and test evidence"):
        return routing.record_route(self.c, run_id, outcome, self.evidence(run_id, outcome, report), "Synthetic human")

    def test_reference_profiles_are_unverified_and_explicit(self):
        profile = routing.default_model_profile("claude")
        self.assertEqual(profile["planner"]["model_id"], "claude-opus-4-8")
        self.assertEqual(profile["recovery"]["model_id"], "claude-sonnet-5")
        self.expect("ROUTE_CONFIG", routing.initialize_route, self.c, "TASK-001", "claude", profile)
        self.assertEqual(routing.default_model_profile("cursor")["planner"]["model_id"], "")

    def test_moving_alias_or_wrong_requested_role_rejected(self):
        for model in ("opus", "auto", "--skip-permissions", "x\n--model"):
            bad = copy.deepcopy(self.profile)
            bad["planner"]["model_id"] = model
            self.expect("ROUTE_CONFIG", routing.initialize_route, self.c, "TASK-001", "claude", bad)
        bad = copy.deepcopy(self.profile)
        bad["planner"]["requested_model"] = "Opus 5"
        self.expect("ROUTE_CONFIG", routing.initialize_route, self.c, "TASK-001", "claude", bad)

    def test_verification_date_expired_naive_future_invalid(self):
        for date in ("2020-01-01T00:00:00+00:00", "2026-09-09T00:00:00", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "invalid"):
            bad = copy.deepcopy(self.profile)
            bad["builder"]["verified_at"] = date
            self.expect("ROUTE_CONFIG", routing.initialize_route, self.c, "TASK-001", "claude", bad)

    def test_route_requires_reviewed_current_task(self):
        review = core.state_path(self.c, "source_review.json")
        review.unlink()
        core.sync(self.c)
        self.expect("ROUTE_REVIEW", self.start)

    def test_plan_command_prepared_with_pinned_id_restricted_tools(self):
        run = self.start()
        prepared = routing.next_route(self.c, run)
        self.assertEqual(prepared["stage"], "PLAN")
        self.assertEqual(prepared["argv"][:3], ["claude", "--model", "claude-opus-4-8"])
        self.assertIn("--strict-mcp-config", prepared["argv"])
        self.assertIn("Read,Glob,Grep", prepared["argv"])
        self.assertNotIn("--dangerously-skip-permissions", prepared["argv"])
        self.assertEqual(prepared["model_calls"], 0)
        self.assertLessEqual(prepared["handoff_bytes"], routing.MAX_PROMPT_BYTES)
        self.assertEqual(routing.next_route(self.c, run)["step_id"], prepared["step_id"])

    def test_full_happy_path_requires_separate_human_acceptance(self):
        run = self.start()
        self.assertEqual(self.record(run, "plan-approved")["stage"], "BUILD")
        self.assertEqual(self.record(run, "build-passed")["stage"], "REVIEW")
        self.assertEqual(self.record(run, "review-passed")["stage"], "ACCEPTANCE")
        human = routing.next_route(self.c, run)
        self.assertIsNone(human["argv"])
        result = self.record(run, "accepted")
        self.assertEqual(result["stage"], "COMPLETE")
        self.assertEqual(result["business_acceptance"], "ACCEPTED_HUMAN_REPORTED")
        self.assertEqual(result["kind"], "HUMAN_REPORTED")

    def test_two_failed_haiku_attempts_trigger_one_sonnet_recovery(self):
        run = self.start()
        self.record(run, "plan-approved")
        first = self.record(run, "build-failed")
        self.assertEqual((first["stage"], first["failed_candidates"]), ("BUILD", 1))
        second = self.record(run, "build-failed")
        self.assertEqual((second["stage"], second["failed_candidates"]), ("RECOVERY", 2))
        self.assertEqual(routing.next_route(self.c, run)["model_id"], "claude-sonnet-5")
        result = self.record(run, "build-failed")
        self.assertEqual((result["stage"], result["recovery_attempts"]), ("STOPPED", 1))
        self.assertIsNone(routing.next_route(self.c, run)["argv"])

    def test_recovery_success_still_requires_opus_review(self):
        run = self.start()
        for outcome in ("plan-approved", "build-failed", "build-failed", "build-passed"):
            self.record(run, outcome)
        prepared = routing.next_route(self.c, run)
        self.assertEqual((prepared["stage"], prepared["model_id"]), ("REVIEW", "claude-opus-4-8"))
        self.assertEqual(self.record(run, "review-failed")["stage"], "STOPPED")

    def test_review_failure_consumes_candidate_budget(self):
        run = self.start()
        for outcome in ("plan-approved", "build-passed", "review-failed", "build-passed", "review-failed"):
            result = self.record(run, outcome)
        self.assertEqual(result["stage"], "RECOVERY")
        self.assertEqual(result["build_attempts"], 2)
        self.assertEqual(result["failed_candidates"], 2)

    def test_cursor_uses_composer_and_stops_after_two_failures(self):
        run = self.start("cursor")
        plan = routing.next_route(self.c, run)
        self.assertEqual(plan["argv"][:3], ["agent", "--model", "account-opus-4.8"])
        self.assertIn("plan", plan["argv"])
        self.record(run, "plan-approved")
        builder = routing.next_route(self.c, run)
        self.assertEqual(builder["argv"][:3], ["agent", "--model", "composer-2.5"])
        self.assertNotIn("--force", builder["argv"])
        self.record(run, "build-failed")
        self.assertEqual(self.record(run, "build-failed")["stage"], "STOPPED")

    def test_scoped_code_changes_do_not_reset_failure_budget(self):
        run = self.start()
        self.record(run, "plan-approved")
        self.record(run, "build-failed")
        routing.next_route(self.c, run)
        (Path(self.c["repo_path"]) / "src" / "new.py").write_text("value = 1\n")
        self.expect("ROUTE_STALE", routing.next_route, self.c, run)
        core.sync(self.c)
        self.expect("ROUTE_PENDING", routing.next_route, self.c, run)
        result = self.record(run, "build-failed")
        self.assertEqual((result["stage"], result["failed_candidates"]), ("RECOVERY", 2))
        restarted = routing.initialize_route(self.c, "TASK-001", "claude", self.profile)
        self.assertEqual(restarted["run_id"], run)
        self.assertTrue(restarted["existing"])

    def test_model_changes_cannot_restart_budget(self):
        run = self.start()
        changed = copy.deepcopy(self.profile)
        changed["builder"]["model_id"] = "another-haiku-version"
        self.expect("ROUTE_CONFIG", routing.initialize_route, self.c, "TASK-001", "claude", changed)
        self.assertEqual(run, self.start())

    def test_business_source_change_stops_old_plan_after_refresh(self):
        run = self.start()
        self.record(run, "plan-approved")
        pages = read_json(Path(self.c["fixture_path"]))
        pages[0]["markdown"] += "\nChanged synthetic approved business meaning.\n"
        atomic_json(Path(self.c["fixture_path"]), pages)
        health = core.sync(self.c)
        core.acknowledge_source(self.c, health["source_hash"], "Synthetic reviewer")
        core.sync(self.c)
        self.expect("ROUTE_CHANGED", routing.next_route, self.c, run)
        self.assertEqual(routing.next_route(self.c, run)["stage"], "STOPPED")

    def test_candidate_edit_after_review_invalidates_acceptance(self):
        run = self.start()
        for outcome in ("plan-approved", "build-passed", "review-passed"):
            self.record(run, outcome)
        (Path(self.c["repo_path"]) / "src" / "late.py").write_text("value = 2\n")
        core.sync(self.c)
        self.expect("ROUTE_CHANGED", routing.next_route, self.c, run)

    def test_unallowed_observed_file_change_stops_route(self):
        run = self.start()
        self.record(run, "plan-approved")
        routing.next_route(self.c, run)
        (Path(self.c["repo_path"]) / "pyproject.toml").write_text("[project]\nname='out-of-scope'\n")
        core.sync(self.c)
        self.expect("ROUTE_SCOPE", self.record, run, "build-passed")

    def test_wrong_stage_and_missing_handoff_rejected(self):
        run = self.start()
        self.expect("ROUTE_STAGE", routing.record_route, self.c, run, "plan-approved", self.root / "missing", "Human")
        routing.next_route(self.c, run)
        self.expect("ROUTE_STAGE", routing.record_route, self.c, run, "accepted", self.root / "missing", "Human")

    def test_duplicate_record_cannot_advance_twice(self):
        run = self.start()
        path = self.evidence(run, "plan-approved")
        routing.record_route(self.c, run, "plan-approved", path, "Human")
        self.expect("ROUTE_STAGE", routing.record_route, self.c, run, "plan-approved", path, "Human")

    def test_model_substitution_rejected_but_can_record_blocked_truthfully(self):
        run = self.start()
        path = self.evidence(run, "plan-approved")
        payload = read_json(path)
        payload["actual_model_id"] = "claude-opus-5"
        atomic_json(path, payload)
        self.expect("ROUTE_MODEL", routing.record_route, self.c, run, "plan-approved", path, "Human")
        payload["outcome"] = "blocked"
        atomic_json(path, payload)
        result = routing.record_route(self.c, run, "blocked", path, "Human")
        self.assertEqual(result["stage"], "STOPPED")
        self.assertEqual(result["failed_candidates"], 0)

    def resume(self, run_id):
        template = routing.next_route(self.c, run_id)["resume_evidence_template"]
        template.update(summary="Human confirmed access restored for the exact configured model.", report_path="restored.md")
        evidence = self.root / "resume-evidence.json"
        atomic_json(evidence, template)
        (self.root / "restored.md").write_text("Authentication now succeeds. Task and candidate unchanged.", encoding="utf-8")
        return routing.resume_route(self.c, run_id, evidence, "Synthetic human")

    def test_blocked_prerequisite_can_resume_without_resetting_failed_attempt(self):
        run = self.start()
        self.record(run, "plan-approved")
        self.record(run, "build-failed")
        self.record(run, "blocked", "Usage unavailable; no code/test result obtained.")
        restored = self.resume(run)
        self.assertEqual((restored["stage"], restored["failed_candidates"], restored["build_attempts"]), ("BUILD", 1, 1))
        self.assertEqual(self.record(run, "build-failed")["stage"], "RECOVERY")

    def test_blocked_recovery_resumes_same_single_attempt(self):
        run = self.start()
        for outcome in ("plan-approved", "build-failed", "build-failed", "blocked"):
            self.record(run, outcome)
        restored = self.resume(run)
        self.assertEqual((restored["stage"], restored["recovery_attempts"]), ("RECOVERY", 0))
        result = self.record(run, "build-failed")
        self.assertEqual((result["stage"], result["recovery_attempts"]), ("STOPPED", 1))
        self.expect("ROUTE_STAGE", routing.resume_route, self.c, run, self.root / "absent", "Human")

    def test_rejected_route_cannot_resume(self):
        run = self.start()
        self.record(run, "plan-rejected")
        self.expect("ROUTE_STAGE", routing.resume_route, self.c, run, self.root / "absent", "Human")

    def test_resume_refuses_changed_candidate(self):
        run = self.start()
        self.record(run, "blocked")
        (Path(self.c["repo_path"]) / "src" / "change.py").write_text("change = True\n")
        core.sync(self.c)
        self.expect("ROUTE_CHANGED", self.resume, run)

    def test_completed_record_names_historical_accepted_candidate(self):
        run = self.start()
        for outcome in ("plan-approved", "build-passed", "review-passed", "accepted"):
            last = self.record(run, outcome)
        (Path(self.c["repo_path"]) / "src" / "later.py").write_text("later = True\n")
        result = routing.next_route(self.c, run)
        self.assertTrue(result["historical_result"])
        self.assertEqual(result["candidate_code_hash"], last["candidate_code_hash"])

    def test_wrong_step_or_candidate_evidence_rejected(self):
        run = self.start()
        for key, value in (("step_id", "STEP-900"), ("code_hash", "wrong"), ("run_id", "RUN-wrong")):
            path = self.evidence(run, "plan-approved")
            payload = read_json(path)
            payload[key] = value
            atomic_json(path, payload)
            self.expect("ROUTE_EVIDENCE", routing.record_route, self.c, run, "plan-approved", path, "Human")

    def test_saved_evidence_and_handoff_tampering_detected(self):
        run = self.start()
        self.record(run, "plan-approved")
        path = routing._route_dir(self.c, run) / "STEP-001-report.md"
        path.write_text("tampered", encoding="utf-8")
        self.expect("ROUTE_INTEGRITY", routing.next_route, self.c, run)

    def test_pending_handoff_tampering_detected(self):
        run = self.start()
        prepared = routing.next_route(self.c, run)
        Path(prepared["handoff_path"]).write_text("tampered", encoding="utf-8")
        self.expect("ROUTE_INTEGRITY", routing.next_route, self.c, run)
        self.expect("ROUTE_INTEGRITY", self.record, run, "plan-approved")

    def test_oversized_or_secret_report_rejected(self):
        run = self.start()
        for report in ("x" * (routing.MAX_REPORT_BYTES + 1), "-----BEGIN PRIVATE KEY-----"):
            self.expect("ROUTE_EVIDENCE", self.record, run, "plan-approved", report)

    def test_report_relative_path_escape_rejected(self):
        run = self.start()
        path = self.evidence(run, "plan-approved")
        payload = read_json(path)
        payload["report_path"] = "../outside.md"
        atomic_json(path, payload)
        self.expect("PATH_ESCAPE", routing.record_route, self.c, run, "plan-approved", path, "Human")

    def test_oversized_next_handoff_does_not_commit_stage_progression(self):
        run = self.start()
        prepared = routing.next_route(self.c, run)
        path = self.evidence(run, "plan-approved", "Plan detail. " * 500)
        with patch.object(routing, "MAX_PROMPT_BYTES", prepared["handoff_bytes"] + 100):
            self.expect("ROUTE_BUDGET", routing.record_route, self.c, run, "plan-approved", path, "Human")
        ledger = read_json(routing._route_dir(self.c, run) / "ledger.json")
        self.assertEqual(ledger["stage"], "PLAN")
        self.assertEqual(ledger["events"], [])
        result = self.record(run, "plan-approved", "Small scoped plan with concrete tests.")
        self.assertEqual(result["stage"], "BUILD")

    def test_invalid_run_identity_cannot_escape_state(self):
        self.expect("ROUTE", routing.next_route, self.c, "../../x")

    def test_config_profile_supported_without_direct_models_arg(self):
        self.c["routing"] = {"models": {"claude": self.profile}}
        health = core.sync(self.c)
        core.acknowledge_source(self.c, health["source_hash"], "Synthetic reviewer")
        core.sync(self.c)
        result = routing.initialize_route(self.c, "TASK-001", "claude")
        self.assertEqual(result["stage"], "PLAN")

    def test_freshness_expiry_blocks_preparation(self):
        run = self.start()
        path = core.state_path(self.c, "health.json")
        health = read_json(path)
        health["checked_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        atomic_json(path, health)
        self.expect("ROUTE_STALE", routing.next_route, self.c, run)


if __name__ == "__main__":
    unittest.main()
