import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from work_context import core
from work_context.common import BridgeError, atomic_json, digest, read_json


class BridgeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        initialized = core.initialize(self.root / "Work Vault", "forecast-automation", self.root / "State", True)
        self.config_path = Path(initialized["config_path"])
        self.c = core.load_config(self.config_path)

    def expect_error(self, code, callable_, *args):
        with self.assertRaises(BridgeError) as caught:
            callable_(*args)
        self.assertEqual(caught.exception.code, code)

    def change_source(self, transform):
        fixture = Path(self.c["fixture_path"])
        pages = read_json(fixture)
        transform(pages)
        atomic_json(fixture, pages)

    def test_end_to_end_shared_files_and_zero_model_calls(self):
        health = core.sync(self.c)
        self.assertEqual(health["state"], "FRESH")
        self.assertEqual(health["review_status"], "REVIEW_REQUIRED")
        self.assertEqual(health["model_calls"], 0)
        cursor = core.packet(self.c, "cursor")
        body = Path(cursor["path"]).read_text(encoding="utf-8")
        self.assertIn("BR-001", body)
        self.assertIn("AC-001", body)
        self.assertIn("grants no execution", body)
        self.assertTrue(Path(self.c["project_path"]).joinpath("context", "START_HERE.md").exists())

    def test_unchanged_capture_reuses_release(self):
        first = core.sync(self.c)
        path = Path(first["packet_path"]).parent / "manifest.json"
        original = path.read_bytes()
        second = core.sync(self.c)
        self.assertEqual(first["bundle_id"], second["bundle_id"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(path.parent.parent.iterdir())), 1)

    def test_scoped_code_edit_keeps_source_acknowledgment(self):
        first = core.sync(self.c)
        core.acknowledge_source(self.c, first["source_hash"], "Synthetic reviewer")
        acknowledged = core.sync(self.c)
        (Path(self.c["repo_path"]) / "src" / "mapping.py").write_text("def validate(): return True\n")
        self.assertEqual(core.status(self.c)["state"], "STALE")
        changed = core.sync(self.c)
        self.assertEqual(changed["review_status"], "REVIEW_ACKNOWLEDGED_LOCAL")
        self.assertEqual(changed["source_hash"], acknowledged["source_hash"])
        self.assertNotEqual(changed["bundle_id"], acknowledged["bundle_id"])

    def test_business_change_invalidates_acknowledgment(self):
        first = core.sync(self.c)
        core.acknowledge_source(self.c, first["source_hash"], "Reviewer")
        self.change_source(lambda p: p[0].update(markdown=p[0]["markdown"] + "\nUse the newly reviewed tolerance.\n"))
        changed = core.sync(self.c)
        self.assertEqual(changed["review_status"], "REVIEW_REQUIRED")
        self.assertNotEqual(changed["source_hash"], first["source_hash"])

    def test_missing_rule_invalidates_active_pointer(self):
        core.sync(self.c)
        self.change_source(lambda p: p[0].update(markdown=p[0]["markdown"].replace("BR-001", "BR-002")))
        self.expect_error("MISSING_REQUIREMENT", core.sync, self.c)
        self.assertEqual(core.status(self.c)["state"], "INCOMPLETE")
        self.expect_error("STALE", core.packet, self.c, "cursor")
        pointer = core.context_path(self.c, "START_HERE.md").read_text()
        self.assertNotIn("releases/", pointer)

    def test_row_metadata_drives_dependencies(self):
        row = {"id": "rule", "external_id": "BR-001", "title": "Unique mapping", "markdown": "Reject duplicate mapping keys.", "classification": "Internal", "status": "Approved", "requirement_type": "Rule", "depends_on_ids": ["CON-001"]}
        ac = {**row, "id": "acceptance", "external_id": "AC-001", "requirement_type": "Acceptance", "markdown": "Run missing/blank/duplicate examples.", "depends_on_ids": ["BR-001"]}
        constraint = {**row, "id": "constraint", "external_id": "CON-001", "requirement_type": "Constraint", "markdown": "Do not discard any source rows.", "depends_on_ids": []}
        atomic_json(Path(self.c["fixture_path"]), [row, ac, constraint])
        result = core.sync(self.c)
        manifest = core.check_release(self.c, result["bundle_id"])
        self.assertIn("CON-001", manifest["requirement_ids"])
        self.assertIn("Do not discard", Path(result["packet_path"]).read_text())

    def test_draft_requirement_cannot_be_acknowledged(self):
        self.change_source(lambda p: p[0].update(requirement_type="Rule", status="Draft"))
        result = core.sync(self.c)
        self.expect_error("REVIEW_MISMATCH", core.acknowledge_source, self.c, result["source_hash"], "Reviewer")

    def test_duplicate_rule_ids_fail(self):
        self.change_source(lambda p: p.append({**p[0], "id": "second-page"}))
        self.expect_error("DUPLICATE_ID", core.sync, self.c)

    def test_blank_or_mismatched_requirement_type_is_rejected(self):
        self.change_source(lambda p: p[0].update(external_id="BR-001", requirement_type="", status="Draft"))
        self.expect_error("INCOMPLETE", core.sync, self.c)

    def test_policy_changes_invalidate_existing_packet(self):
        core.sync(self.c)
        self.c["allowed_classifications"] = ["Restricted"]
        self.assertEqual(core.status(self.c)["state"], "STALE")
        self.expect_error("STALE", core.packet, self.c, "cursor")

    def test_failed_capture_cannot_be_acknowledged(self):
        result = core.sync(self.c)
        self.change_source(lambda p: p[0].update(truncated=True))
        self.expect_error("INCOMPLETE", core.sync, self.c)
        self.expect_error("REVIEW_MISMATCH", core.acknowledge_source, self.c, result["source_hash"], "Reviewer")

    def test_budget_never_silently_drops_rule(self):
        self.c["max_packet_bytes"] = 100
        self.expect_error("CONTEXT_TOO_LARGE", core.sync, self.c)
        self.assertFalse(core.state_path(self.c, "current.json").exists())

    def test_known_secret_fails_before_source_cache(self):
        self.change_source(lambda p: p[0].update(markdown=p[0]["markdown"] + "\nsk-ant-" + "a" * 40))
        self.expect_error("SECRET_DETECTED", core.sync, self.c)
        self.assertFalse(core.state_path(self.c, "candidate_source.json").exists())
        self.assertEqual(core.status(self.c)["state"], "FAILED")

    def test_unknown_content_and_classification_fail_closed(self):
        self.change_source(lambda p: p[0].update(truncated=True))
        self.expect_error("INCOMPLETE", core.sync, self.c)
        self.change_source(lambda p: p[0].update(truncated=False, classification="Restricted"))
        self.expect_error("CLASSIFICATION", core.sync, self.c)

    def test_notional_revocation_quarantines_old_packets(self):
        core.sync(self.c)
        self.c["mode"] = "notion"
        self.c["notion"]["page_ids"] = ["00000000-0000-4000-8000-000000000001"]
        class Revoked:
            def fetch_pages(self, page_ids):
                raise BridgeError("NOTION_ACCESS", "Source unavailable")
        self.expect_error("NOTION_ACCESS", core.sync, self.c, "TASK-001", Revoked())
        self.assertEqual(core.status(self.c)["state"], "UNAVAILABLE")
        self.assertFalse(core.context_path(self.c, "releases").exists())
        self.assertTrue(list(core.state_path(self.c, "quarantine").iterdir()))

    def test_packet_integrity_detects_modified_file_and_manifest(self):
        result = core.sync(self.c)
        packet = Path(result["packet_path"])
        original = packet.read_bytes()
        packet.write_text("edited")
        self.expect_error("INTEGRITY", core.check_release, self.c, result["bundle_id"])
        packet.write_bytes(original)
        manifest_path = packet.parent / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["task"]["goal"] = "Changed goal"
        atomic_json(manifest_path, manifest)
        self.expect_error("INTEGRITY", core.check_release, self.c, result["bundle_id"])

    def test_freshness_expiry_refuses_packet(self):
        core.sync(self.c)
        health_path = core.state_path(self.c, "health.json")
        health = read_json(health_path)
        health["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        atomic_json(health_path, health)
        self.assertEqual(core.status(self.c)["state"], "STALE")
        self.expect_error("STALE", core.packet, self.c, "claude")

    def test_local_capture_error_does_not_leave_fresh_state(self):
        core.sync(self.c)
        with patch.object(core, "repo_fingerprint", side_effect=OSError("example")):
            self.expect_error("CAPTURE_FAILED", core.sync, self.c)
        self.assertEqual(core.status(self.c)["state"], "STALE")

    def test_draft_truthful_and_hash_bound(self):
        core.sync(self.c)
        result = core.draft_update(self.c, "Pilot update", "Prepared a mapping-validation task.")
        draft = read_json(Path(result["draft_path"]))
        self.assertEqual(draft["payload_hash"], digest({k: draft[k] for k in ("external_id", "title", "markdown")}))
        self.assertIn("Technical verification: NOT_RUN", draft["markdown"])
        self.assertTrue(Path(result["draft_path"]).is_relative_to(Path(self.c["state_dir"])))

    def test_state_is_separate_and_owned_by_one_project(self):
        self.expect_error("STATE_LOCATION", core.initialize, self.root / "Unsafe Vault", "sample", self.root / "Unsafe Vault" / "State")
        self.expect_error("STATE_MISMATCH", core.initialize, self.root / "Other Vault", "forecast-automation", self.root / "State", True)
        self.assertNotEqual(core.default_state_dir("same", self.root / "a"), core.default_state_dir("same", self.root / "b"))

    def test_config_cannot_redirect_repository_outside_project(self):
        c = copy.deepcopy(self.c)
        c["repo_path"] = str(self.root / "Outside")
        atomic_json(self.config_path, c)
        self.expect_error("PATH_ESCAPE", core.load_config, self.config_path)

    def test_task_path_and_scope_traversal_are_rejected(self):
        self.expect_error("TASK", core.load_task, self.c, "../../outside")
        task_path = Path(self.c["repo_path"]) / "tasks" / "TASK-001" / "task.json"
        task = read_json(task_path)
        task["allowed_files"] = ["../outside"]
        atomic_json(task_path, task)
        self.expect_error("PATH_ESCAPE", core.sync, self.c)

    def test_inbox_and_notes_never_enter_packet(self):
        Path(self.c["project_path"]).joinpath("notes", "private.md").write_text("UNIQUE_NOTE_SHOULD_NOT_APPEAR")
        result = core.sync(self.c)
        self.assertNotIn("UNIQUE_NOTE_SHOULD_NOT_APPEAR", Path(result["packet_path"]).read_text())

    def test_unconfigured_setup_does_not_call_notion(self):
        other = core.initialize(self.root / "Empty Vault", "new-project", self.root / "New State")
        c = core.load_config(Path(other["config_path"]))
        self.expect_error("NOT_CONFIGURED", core.sync, c)


if __name__ == "__main__":
    unittest.main()
