import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from work_context import core, refresh
from work_context.common import BridgeError, read_json


class RefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        result = core.initialize(self.root / "Local Workspace $literal", "sample", self.root / "Private State", True)
        self.config_path = Path(result["config_path"])
        self.c = core.load_config(self.config_path)

    def test_fixture_refresh_makes_no_network_or_model_calls(self):
        with patch("work_context.notion.NotionClient.call", side_effect=AssertionError("No network")):
            result = refresh.refresh(self.c)
        self.assertEqual(result["state"], "FRESH")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["shared"]["status"], "not_configured")
        self.assertFalse(result["source_review_automated"])
        self.assertEqual(read_json(core.state_path(self.c, "refresh-health.json"))["state"], "FRESH")

    def test_keychain_lookup_is_memory_only_and_uses_separate_arguments(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(refresh.sys, "platform", "darwin"), patch.object(refresh.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"synthetic-token\n", b"")) as run:
            client = refresh.read_client(self.c, "Company.Notion.Read", "work-user")
            self.assertEqual(client._token, "synthetic-token")
            self.assertNotIn("NOTION_READ_TOKEN", os.environ)
        self.assertEqual(run.call_args.args[0], ["/usr/bin/security", "find-generic-password", "-s", "Company.Notion.Read", "-a", "work-user", "-w"])
        self.assertNotIn("synthetic-token", str(run.call_args))

    def test_existing_process_credential_needs_no_keychain(self):
        with patch.dict(os.environ, {"NOTION_READ_TOKEN": "synthetic-token"}), patch.object(refresh.subprocess, "run", side_effect=AssertionError("No process")):
            self.assertEqual(refresh.read_client(self.c)._token, "synthetic-token")

    def test_keychain_failure_invalidates_old_context_without_exposing_output(self):
        first = core.sync(self.c)
        self.c["mode"] = "notion"
        self.c["notion"]["page_ids"] = ["00000000-0000-4000-8000-000000000001"]
        with patch.dict(os.environ, {}, clear=True), patch.object(refresh.sys, "platform", "darwin"), patch.object(refresh.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"do-not-log", b"private-error")):
            with self.assertRaises(BridgeError) as caught:
                refresh.refresh(self.c, keychain_service="Company.Notion.Read", keychain_account="work-user")
        self.assertEqual(caught.exception.code, "AUTH_REQUIRED")
        self.assertFalse(Path(first["packet_path"]).exists())
        diagnostics = core.state_path(self.c, "refresh-health.json").read_text()
        self.assertNotIn("do-not-log", diagnostics)
        self.assertNotIn("private-error", diagnostics)
        self.assertEqual(core.status(self.c)["state"], "UNAVAILABLE")

    def test_schedule_is_offline_reviewed_export_with_no_secret_values(self):
        with patch.dict(os.environ, {"NOTION_READ_TOKEN": "synthetic-secret-value"}), patch.object(refresh.subprocess, "run", side_effect=AssertionError("No execution")):
            plan = refresh.schedule_plan(self.c, self.config_path, keychain_service="Company.Notion.Read", keychain_account="work-user")
            self.assertFalse(Path(plan["output_path"]).exists())
            self.assertNotIn("synthetic-secret-value", str(plan))
            result = refresh.export_schedule(self.c, plan, plan["reviewed_operation_hash"])
        self.assertFalse(result["installed"])
        plist = plistlib.loads(Path(result["plist_path"]).read_bytes())
        self.assertEqual(plist["StartInterval"], 300)
        self.assertEqual(plist["ProgramArguments"][0], str(Path(sys.executable).resolve()))
        self.assertIn(str(self.config_path), plist["ProgramArguments"])
        self.assertNotIn("EnvironmentVariables", plist)
        self.assertTrue(Path(result["plist_path"]).is_relative_to(Path(self.c["state_dir"])))

    def test_failed_shared_invalidation_cannot_leave_fresh_refresh_diagnostic(self):
        refresh.refresh(self.c)
        self.c["shared"] = {"member_id": "luke", "publisher_id": "luke"}
        with patch.object(core, "sync", side_effect=BridgeError("ACCESS_REVOKED", "Source revoked")), patch("work_context.shared.invalidate_shared", side_effect=BridgeError("SHARED_QUARANTINE", "Shared path unavailable")):
            with self.assertRaises(BridgeError) as caught:
                refresh.refresh(self.c)
        self.assertEqual(caught.exception.code, "SHARED_INVALIDATION_PENDING")
        diagnostic = read_json(core.state_path(self.c, "refresh-health.json"))
        self.assertEqual(diagnostic["state"], "FAILED")
        self.assertEqual(diagnostic["shared"]["status"], "invalidation_pending")

    def test_changed_plan_or_bad_hash_cannot_export(self):
        plan = refresh.schedule_plan(self.c, self.config_path)
        with self.assertRaises(BridgeError):
            refresh.export_schedule(self.c, plan, "wrong")
        plan["plist"]["ProgramArguments"].append("--different")
        with self.assertRaises(BridgeError):
            refresh.export_schedule(self.c, plan, plan["reviewed_operation_hash"])
        self.assertFalse(Path(plan["output_path"]).exists())

    def test_invalid_interval_and_credential_reference_are_rejected(self):
        for interval in (0, 59, 900, 86401, True):
            with self.subTest(interval=interval), self.assertRaises(BridgeError):
                refresh.schedule_plan(self.c, self.config_path, interval=interval)
        for service, account in (("Only.Service", None), ("$(command)", "work-user"), ("-bad", "work-user")):
            with self.subTest(service=service), self.assertRaises(BridgeError):
                refresh.schedule_plan(self.c, self.config_path, keychain_service=service, keychain_account=account)


if __name__ == "__main__":
    unittest.main()
