import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from work_context import core
from work_context.cli import main, notion_id
from work_context.common import BridgeError, atomic_json, read_json


class CLITests(unittest.TestCase):
    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, json.loads(out.getvalue() or err.getvalue())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        code, result = self.run_cli(["init", "--vault", str(root / "Work Vault"), "--state-dir", str(root / "State"), "--demo"])
        self.assertEqual(code, 0)
        self.config = result["config_path"]

    def cmd(self, *args):
        return self.run_cli(["--config", self.config, *args])

    def test_cli_demo_sync_review_packet_draft(self):
        code, result = self.cmd("sync")
        self.assertEqual(code, 0)
        code, review = self.cmd("approve-source", "--reviewed-hash", result["source_hash"], "--actor", "Demo Reviewer")
        self.assertEqual(code, 0)
        self.assertEqual(review["kind"], "LOCAL_REVIEW_ACKNOWLEDGMENT")
        self.cmd("sync")
        self.assertEqual(self.cmd("packet", "--for", "claude")[0], 0)
        code, draft = self.cmd("draft-update", "--title", "Context prepared", "--summary", "Synthetic requirements captured.")
        self.assertEqual(code, 0)
        self.assertTrue(Path(draft["draft_path"]).exists())
        code, publish = self.cmd("publish", "--draft", draft["draft_path"], "--data-source-id", "00000000-0000-4000-8000-000000000003")
        self.assertEqual(code, 0)
        self.assertIn("reviewed_operation_hash", publish)

    def test_notion_plan_is_complete_without_connection(self):
        code, plan = self.run_cli(["notion-plan", "--parent-page", "https://www.notion.so/Work-00000000000040008000000000000001"])
        self.assertEqual(code, 0)
        self.assertEqual(len(plan["databases"]), 5)
        self.assertEqual(plan["model_calls"], 0)

    def test_notion_configuration_requires_scope_acknowledgment(self):
        args = ("configure-notion", "--page-id", "00000000-0000-4000-8000-000000000001")
        code, result = self.cmd(*args)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "SCOPE_REQUIRED")
        code, result = self.cmd(*args, "--reviewed-scope")
        self.assertEqual(code, 0)
        self.assertEqual(result["mode"], "notion")
        self.assertEqual(self.cmd("status")[1]["state"], "STALE")

    def test_apply_without_review_hash_does_not_reach_network(self):
        with patch("work_context.notion.NotionClient.call", side_effect=AssertionError("Unexpected network")):
            code, result = self.cmd("notion-bootstrap", "--parent-page", "00000000-0000-4000-8000-000000000001", "--apply")
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "REVIEW_MISMATCH")

    def test_non_notion_url_is_rejected(self):
        with self.assertRaises(BridgeError):
            notion_id("https://example.org/00000000000040008000000000000001")


if __name__ == "__main__":
    unittest.main()
