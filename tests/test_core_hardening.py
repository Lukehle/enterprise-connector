import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from work_context import core
from work_context.common import BridgeError, atomic_json, read_json


class CoreHardeningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        result = core.initialize(self.root / "Work Vault", "sample", self.root / "State", True)
        self.c = core.load_config(Path(result["config_path"]))

    def test_nested_source_directories_are_hashed(self):
        for name in ("tasks", "docs", "context"):
            with self.subTest(name=name):
                path = Path(self.c["repo_path"]) / "src" / name / "job.py"
                path.parent.mkdir(parents=True)
                path.write_text("original\n")
                core.sync(self.c)
                path.write_text("changed\n")
                self.assertEqual(core.status(self.c)["state"], "STALE")

    def test_allowed_files_extend_fingerprint_scope(self):
        path = Path(self.c["repo_path"]) / "reports" / "mapping.sql"
        path.parent.mkdir()
        path.write_text("SELECT 1;\n")
        task_path = Path(self.c["repo_path"]) / "tasks" / "TASK-001" / "task.json"
        task = read_json(task_path)
        task["allowed_files"].append("reports/**")
        atomic_json(task_path, task)
        core.sync(self.c)
        path.write_text("SELECT 2;\n")
        self.assertEqual(core.status(self.c)["state"], "STALE")

    def test_walk_failure_invalidates_persisted_health(self):
        core.sync(self.c)
        def broken_walk(*args, **kwargs):
            kwargs["onerror"](PermissionError("unreadable directory"))
            return iter(())
        with patch.object(core.os, "walk", side_effect=broken_walk):
            with self.assertRaises(BridgeError):
                core.status(self.c)
        self.assertNotEqual(read_json(core.state_path(self.c, "health.json"))["state"], "FRESH")
        self.assertNotIn("releases/", core.context_path(self.c, "START_HERE.md").read_text())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_fifo_is_rejected_without_opening(self):
        os.mkfifo(Path(self.c["repo_path"]) / "src" / "pipe")
        with self.assertRaises(BridgeError) as caught:
            core.sync(self.c)
        self.assertEqual(caught.exception.code, "REPOSITORY")

    def test_quarantine_failure_blocks_existing_and_new_packets(self):
        first = core.sync(self.c)
        core.acknowledge_source(self.c, first["source_hash"], "Reviewer")
        core.sync(self.c)
        with patch.object(core.shutil, "move", side_effect=PermissionError("locked packet")):
            core.record_failure(self.c, BridgeError("NOTION_ACCESS", "Source access lost"))
            self.assertTrue(read_json(core.state_path(self.c, "health.json"))["quarantine_pending"])
            with self.assertRaises(BridgeError):
                core.packet(self.c, "cursor")
            with self.assertRaises(BridgeError) as caught:
                core.sync(self.c)
            self.assertEqual(caught.exception.code, "QUARANTINE_PENDING")
        result = core.sync(self.c)
        self.assertEqual(result["review_status"], "REVIEW_REQUIRED")
        self.assertTrue(list(core.state_path(self.c, "quarantine").iterdir()))

    def test_policy_narrowing_quarantines_visible_releases_on_status(self):
        first = core.sync(self.c)
        self.c["allowed_classifications"] = ["Internal"]
        self.assertEqual(core.status(self.c)["state"], "STALE")
        self.assertFalse(Path(first["packet_path"]).exists())

    def test_quarantine_intent_survives_render_failure_and_process_interrupt(self):
        for target, failure in (("render_status", PermissionError("cannot render")), ("shutil.move", KeyboardInterrupt())):
            with self.subTest(target=target):
                first = core.sync(self.c)
                core.acknowledge_source(self.c, first["source_hash"], "Reviewer")
                old = core.sync(self.c)
                with patch("work_context.core." + target, side_effect=failure):
                    with self.assertRaises(type(failure)):
                        core.record_failure(self.c, BridgeError("NOTION_ACCESS", "Source unavailable"))
                self.assertTrue(read_json(core.state_path(self.c, "health.json"))["quarantine_pending"])
                restored = core.sync(self.c)
                self.assertEqual(restored["review_status"], "REVIEW_REQUIRED")
                self.assertFalse(Path(old["packet_path"]).exists())

    def test_explicit_state_tilde_is_expanded(self):
        with patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}):
            result = core.initialize(self.root / "Other Vault", "tilde", Path("~/Tilde State"), True)
        self.assertEqual(Path(result["state_dir"]), self.root / "Tilde State")

    def test_sync_cannot_skip_policy_quarantine(self):
        first = core.sync(self.c)
        self.c["max_packet_bytes"] += 100
        core.sync(self.c)
        self.assertFalse(Path(first["packet_path"]).exists())

    def test_remote_reclassification_quarantines_visible_releases(self):
        first = core.sync(self.c)
        pages = read_json(Path(self.c["fixture_path"]))
        pages[0]["classification"] = "Restricted"
        atomic_json(Path(self.c["fixture_path"]), pages)
        with self.assertRaises(BridgeError):
            core.sync(self.c)
        self.assertFalse(Path(first["packet_path"]).exists())

    def test_rewritten_packet_and_manifest_fail_external_receipt(self):
        first = core.sync(self.c)
        release = Path(first["packet_path"]).parent
        manifest = read_json(release / "manifest.json")
        for name in manifest["file_hashes"]:
            (release / name).write_bytes(b"forged packet")
            manifest["file_hashes"][name] = hashlib.sha256(b"forged packet").hexdigest()
        manifest["verification"] = "PASSED"
        atomic_json(release / "manifest.json", manifest)
        with self.assertRaises(BridgeError) as caught:
            core.status(self.c)
        self.assertEqual(caught.exception.code, "INTEGRITY")
        self.assertEqual(read_json(core.state_path(self.c, "health.json"))["state"], "FAILED")
        self.assertNotIn("releases/", core.context_path(self.c, "START_HERE.md").read_text())

    def test_explicit_repair_restores_corrupted_release(self):
        first = core.sync(self.c)
        Path(first["packet_path"]).write_text("broken")
        with self.assertRaises(BridgeError):
            core.sync(self.c)
        result = core.sync(self.c, repair=True)
        self.assertEqual(result["bundle_id"], first["bundle_id"])
        self.assertEqual(core.status(self.c)["state"], "FRESH")
        self.assertIn("Applicable requirements", Path(result["packet_path"]).read_text())
        self.assertTrue(list(core.state_path(self.c, "quarantine").glob("*-damaged-*")))

    def test_missing_review_receipt_invalidates_acknowledged_packet(self):
        first = core.sync(self.c)
        core.acknowledge_source(self.c, first["source_hash"], "Reviewer")
        core.sync(self.c)
        core.state_path(self.c, "source_review.json").unlink()
        self.assertEqual(core.status(self.c)["state"], "STALE")
        self.assertEqual(core.sync(self.c)["review_status"], "REVIEW_REQUIRED")

    def test_compiler_upgrade_invalidates_capture(self):
        core.sync(self.c)
        with patch.object(core, "__version__", "future"):
            self.assertEqual(core.status(self.c)["state"], "STALE")

    def test_mac_state_directory_is_application_support(self):
        with patch.object(core.sys, "platform", "darwin"):
            path = core.default_state_dir("sample", self.root / "Work Vault")
        self.assertTrue(path.is_relative_to(Path.home() / "Library" / "Application Support" / "WorkContext"))

    @unittest.skipIf(os.name == "nt", "Symlink creation needs a Windows privilege; exercised on Mac/Linux CI")
    def test_internal_symlink_parent_has_consistent_identity(self):
        vault = self.root / "Linked Vault"
        (vault / "Projects Storage").mkdir(parents=True)
        (vault / "10 Projects").symlink_to(vault / "Projects Storage", target_is_directory=True)
        result = core.initialize(vault, "linked", self.root / "Linked State", True)
        config = core.load_config(Path(result["config_path"]))
        self.assertEqual(core.sync(config)["state"], "FRESH")

    def test_update_metadata_changes_identity_and_hash(self):
        core.sync(self.c)
        first = core.draft_update(self.c, "Example", "Synthetic outcome.", "Public")
        second = core.draft_update(self.c, "Example", "Synthetic outcome.", "Internal")
        self.assertNotEqual(first["external_id"], second["external_id"])
        self.assertNotEqual(first["payload_hash"], second["payload_hash"])


if __name__ == "__main__":
    unittest.main()
