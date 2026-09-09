import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from work_context import core, shared
from work_context.common import BridgeError, atomic_json, digest, read_json


class SharedVaultTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.shared = self.root / "Google Drive" / "Work Together"
        self.local = self.root / "Luke Local"
        self.state = self.root / "Luke State"
        self.result = shared.initialize_shared(self.shared, self.local, "pilot", state_dir=self.state, demo=True)
        self.config_path = Path(self.result["config_path"])
        self.c = core.load_config(self.config_path)
        self.public = self.shared / "10 Projects" / "pilot" / "40 Published"

    def reviewed(self):
        result = core.sync(self.c)
        core.acknowledge_source(self.c, result["source_hash"], "Luke")
        return core.sync(self.c)

    def boss(self):
        result = shared.initialize_shared(self.shared, self.root / "Boss Local", "pilot", member_id="boss", state_dir=self.root / "Boss State")
        return core.load_config(Path(result["config_path"]))

    def test_shared_taxonomy_has_no_local_code_or_state(self):
        for relative in ("00 Home/Working Agreement.md", "00 Home/People.md", "00 Home/ID Register.md", "01 Inbox/luke", "01 Inbox/boss", "10 Projects/pilot/10 Notes/luke", "10 Projects/pilot/10 Notes/boss", "10 Projects/pilot/20 Proposals", "10 Projects/pilot/30 Handoffs", "20 Playbooks", "30 Reference", "90 Archive", "_templates/meeting.md", "99 System/shared-vault.json"):
            self.assertTrue((self.shared / relative).exists(), relative)
        names = {p.name for p in self.shared.rglob("*")}
        self.assertTrue(names.isdisjoint({".git", "repo", "config.json", "health.json", "project.lock", ".cursor"}))
        for path in self.shared.rglob("*"):
            if path.is_file():
                self.assertNotIn(str(self.root), path.read_text(encoding="utf-8"))
        self.assertTrue(self.config_path.is_relative_to(self.local))

    def test_boss_join_and_repeated_init_preserve_human_notes_and_identity(self):
        home = self.shared / "00 Home" / "Home.md"
        home.write_text("Human edited home\n")
        first = read_json(self.shared / shared.REGISTRY)
        boss = self.boss()
        self.assertEqual(boss["shared"]["vault_id"], first["vault_id"])
        shared.initialize_shared(self.shared, self.local, "pilot", state_dir=self.state, demo=True)
        self.assertEqual(home.read_text(), "Human edited home\n")
        self.assertEqual(read_json(self.shared / shared.REGISTRY), first)

    def test_duplicate_project_ids_and_overlapping_locations_are_rejected(self):
        with self.assertRaises(BridgeError):
            shared.initialize_shared(self.shared, self.root / "Other", "other", state_dir=self.root / "Other State")
        self.assertFalse((self.shared / "10 Projects" / "other").exists())
        for local, state in ((self.shared / "local", self.root / "State"), (self.root / "Local2", self.shared / "State"), (self.shared.parent, self.root / "State")):
            with self.subTest(local=local), self.assertRaises(BridgeError):
                shared.initialize_shared(self.shared, local, "other", "PRJ-002", state_dir=state)

    def test_new_project_registration_preserves_other_project_and_human_home(self):
        home = (self.shared / "00 Home/Home.md").read_text()
        result = shared.initialize_shared(self.shared, self.local, "second", "PRJ-002", state_dir=self.root / "Other State")
        self.assertEqual(result["vault_id"], self.result["vault_id"])
        self.assertEqual(set(read_json(self.shared / shared.REGISTRY)["projects"]), {"pilot", "second"})
        self.assertEqual((self.shared / "00 Home/Home.md").read_text(), home)

    def test_member_cannot_rebind_existing_local_profile(self):
        with self.assertRaises(BridgeError) as caught:
            shared.initialize_shared(self.shared, self.local, "pilot", member_id="boss", state_dir=self.state)
        self.assertEqual(caught.exception.code, "SHARED_BINDING")

    def test_existing_local_identity_mismatch_leaves_shared_destination_untouched(self):
        other_shared = self.root / "Uncreated Shared"
        original_local = self.root / "Existing Local"
        original_state = self.root / "Existing State"
        original = core.initialize(original_local, "pilot", state_dir=original_state)
        config_path = Path(original["config_path"])
        before = config_path.read_bytes()
        self.assertNotIn("shared", read_json(config_path))
        for project_id, state in (("PRJ-002", original_state), ("PRJ-001", self.root / "Different State")):
            with self.subTest(project_id=project_id, state=state), self.assertRaises(BridgeError) as caught:
                shared.initialize_shared(other_shared, original_local, "pilot", project_id=project_id, state_dir=state)
            self.assertEqual(caught.exception.code, "SHARED_BINDING")
            self.assertFalse(other_shared.exists())
            self.assertEqual(config_path.read_bytes(), before)

    def test_non_publisher_cannot_publish_or_invalidate(self):
        self.reviewed()
        shared.publish_shared(self.c)
        original = (self.public / "current.json").read_bytes()
        for method in (shared.publish_shared, shared.invalidate_shared):
            with self.subTest(method=method), self.assertRaises(BridgeError) as caught:
                method(self.boss())
            self.assertEqual(caught.exception.code, "SHARED_PUBLISHER")
        self.assertEqual((self.public / "current.json").read_bytes(), original)

    def test_review_is_required_before_publication(self):
        core.sync(self.c)
        with self.assertRaises(BridgeError) as caught:
            shared.publish_shared(self.c)
        self.assertEqual(caught.exception.code, "SHARED_REVIEW")
        self.assertEqual(shared.shared_status(self.c)["state"], "UNAVAILABLE")

    def test_snapshot_is_source_only_and_boss_can_validate_without_notion(self):
        overview = Path(self.c["repo_path"]) / "docs/AI_OVERVIEW.md"
        overview.write_text("UNIQUE LOCAL TECHNICAL OVERVIEW\n")
        self.reviewed()
        result = shared.publish_shared(self.c)
        text = (self.public / "snapshots" / result["publication_id"] / "NOTION_CONTEXT.md").read_text()
        self.assertIn("BR-001", text)
        self.assertIn("AC-001", text)
        self.assertNotIn("UNIQUE LOCAL TECHNICAL OVERVIEW", text)
        self.assertNotIn("Allowed files", text)
        self.assertNotIn(str(self.local), text)
        self.assertEqual(shared.shared_status(self.boss())["state"], "FRESH")

    def test_snapshot_tampering_and_incomplete_cloud_transfer_are_refused(self):
        self.reviewed()
        result = shared.publish_shared(self.c)
        snapshot = self.public / "snapshots" / result["publication_id"]
        content = snapshot / "NOTION_CONTEXT.md"
        original = content.read_bytes()
        content.write_text("tampered")
        with self.assertRaises(BridgeError):
            shared.shared_status(self.c)
        content.write_bytes(original)
        (snapshot / "manifest.json").unlink()
        with self.assertRaises(BridgeError):
            shared.shared_status(self.c)

    def test_old_observation_is_stale_even_with_future_pointer_expiry(self):
        self.reviewed()
        result = shared.publish_shared(self.c)
        with patch.object(shared, "datetime") as fake_time:
            fake_time.now.return_value = datetime.now(timezone.utc) + timedelta(hours=1)
            fake_time.fromisoformat = datetime.fromisoformat
            self.assertEqual(shared.shared_status(self.c)["state"], "STALE")

    def test_reader_classification_restriction_rejects_snapshot(self):
        pages = read_json(Path(self.c["fixture_path"]))
        pages[0]["classification"] = "Internal"
        atomic_json(Path(self.c["fixture_path"]), pages)
        self.reviewed()
        shared.publish_shared(self.c)
        boss = self.boss()
        boss["allowed_classifications"] = ["Public"]
        with self.assertRaises(BridgeError) as caught:
            shared.shared_status(boss)
        self.assertEqual(caught.exception.code, "CLASSIFICATION")

    def test_invalid_pointer_traversal_and_bad_shapes_are_rejected(self):
        self.reviewed()
        shared.publish_shared(self.c)
        pointer_path = self.public / "current.json"
        original = read_json(pointer_path)
        for changes in ({"publication_id": "../../outside"}, {"manifest_hash": []}, {"publisher_epoch": 9}, {"vault_id": "other"}):
            with self.subTest(changes=changes):
                atomic_json(pointer_path, {**original, **changes})
                with self.assertRaises(BridgeError):
                    shared.shared_status(self.c)

    def test_invalidation_removes_generated_content_and_preserves_notes(self):
        self.reviewed()
        shared.publish_shared(self.c)
        note = self.shared / "10 Projects/pilot/10 Notes/luke/human.md"
        note.write_text("Keep this")
        shared.invalidate_shared(self.c, "ACCESS_REVOKED")
        self.assertEqual(shared.shared_status(self.c)["state"], "UNAVAILABLE")
        self.assertFalse((self.public / "snapshots").exists())
        self.assertEqual(note.read_text(), "Keep this")
        self.assertTrue(list((self.state / "quarantine").glob("shared-*")))

    def test_failed_quarantine_is_durable_and_blocks_new_publication(self):
        self.reviewed()
        shared.publish_shared(self.c)
        with patch.object(shared.shutil, "move", side_effect=PermissionError("locked")):
            with self.assertRaises(BridgeError):
                shared.invalidate_shared(self.c, "ACCESS_REVOKED")
            self.assertTrue(read_json(self.state / "shared_invalidation.json")["pending"])
            self.assertEqual(read_json(self.public / "current.json")["state"], "UNAVAILABLE")
            with self.assertRaises(BridgeError):
                shared.publish_shared(self.c)
        shared.invalidate_shared(self.c, "ACCESS_REVOKED")
        self.assertFalse(read_json(self.state / "shared_invalidation.json")["pending"])

    def test_local_paths_in_source_cannot_be_shared(self):
        pages = read_json(Path(self.c["fixture_path"]))
        pages[0]["markdown"] += "\nWork directory /Users/luke/private-data\n"
        atomic_json(Path(self.c["fixture_path"]), pages)
        self.reviewed()
        with self.assertRaises(BridgeError) as caught:
            shared.publish_shared(self.c)
        self.assertEqual(caught.exception.code, "SHARED_CONTENT")
        self.assertFalse((self.public / "snapshots").exists())

    def test_candidate_tampering_invalidates_previous_publication(self):
        self.reviewed()
        shared.publish_shared(self.c)
        path = self.state / "candidate_source.json"
        candidate = read_json(path)
        candidate["pages"][0]["markdown"] += "Tampered"
        atomic_json(path, candidate)
        with self.assertRaises(BridgeError):
            shared.publish_shared(self.c)
        self.assertEqual(shared.shared_status(self.c)["state"], "UNAVAILABLE")

    def test_handover_requires_exact_plan_and_old_epoch_stops_writes(self):
        self.reviewed()
        shared.publish_shared(self.c)
        boss = self.boss()
        plan = shared.transfer_publisher(self.c, "boss")
        with self.assertRaises(BridgeError):
            shared.transfer_publisher(self.c, "boss", reviewed_hash="wrong", apply=True)
        shared.transfer_publisher(self.c, "boss", reviewed_hash=plan["review_hash"], apply=True)
        self.assertEqual(shared.shared_status(boss)["state"], "UNAVAILABLE")
        for profile in (self.c, boss):
            with self.assertRaises(BridgeError) as caught:
                shared.publish_shared(profile)
            self.assertEqual(caught.exception.code, "SHARED_PUBLISHER")
        rebound_boss = self.boss()
        self.assertEqual(rebound_boss["shared"]["publisher_epoch"], 2)
        self.assertEqual(rebound_boss["shared"]["publisher_id"], "boss")

    def test_successful_refresh_retains_three_shared_snapshots(self):
        pages = read_json(Path(self.c["fixture_path"]))
        for number in range(2, 6):
            pages[0]["markdown"] += f"\n## BR-{number:03d} — Extra rule\nSynthetic rule {number}.\n"
        atomic_json(Path(self.c["fixture_path"]), pages)
        self.reviewed()
        task_path = Path(self.c["repo_path"]) / "tasks/TASK-001/task.json"
        for number in range(1, 6):
            task = read_json(task_path)
            task["rule_ids"] = [f"BR-{n:03d}" for n in range(1, number + 1)]
            atomic_json(task_path, task)
            core.sync(self.c)
            shared.publish_shared(self.c)
        self.assertEqual(len(list((self.public / "snapshots").iterdir())), 3)
        self.assertEqual(shared.shared_status(self.c)["state"], "FRESH")

    def test_unchanged_refresh_reuses_snapshot_and_updates_observation(self):
        self.reviewed()
        first = shared.publish_shared(self.c)
        core.sync(self.c)
        second = shared.publish_shared(self.c)
        self.assertEqual(first["publication_id"], second["publication_id"])
        self.assertNotEqual(first["observed_at"], second["observed_at"])
        self.assertEqual(len(list((self.public / "snapshots").iterdir())), 1)
        self.assertEqual(shared.shared_status(self.c)["state"], "FRESH")

    def test_symlink_destinations_are_rejected(self):
        linked = self.shared / "20 Playbooks" / "external"
        outside = self.root / "Outside"
        outside.mkdir()
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation not permitted on this host")
        with self.assertRaises(BridgeError):
            shared._path(self.shared, "20 Playbooks/external/file.md")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO test")
    def test_fifo_metadata_is_rejected_without_reading(self):
        pointer = self.public / "current.json"
        os.mkfifo(pointer)
        with self.assertRaises(BridgeError):
            shared.shared_status(self.c)


if __name__ == "__main__":
    unittest.main()
