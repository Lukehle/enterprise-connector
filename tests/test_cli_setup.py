import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from work_context import core
from work_context.cli import main
from work_context.common import BridgeError, atomic_json, digest, read_json

PAGE = "00000000-0000-4000-8000-000000000001"
DATABASE = "00000000-0000-4000-8000-000000000002"
SOURCE = "00000000-0000-4000-8000-000000000003"


class CLISetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        result = core.initialize(self.root / "Vault", "sample", self.root / "State", True)
        self.config = result["config_path"]
        self.c = core.load_config(Path(self.config))

    def run_cli(self, *arguments, config=True):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main((["--config", self.config] if config else []) + list(arguments))
        return code, json.loads(out.getvalue() or err.getvalue())

    def registry(self):
        registry = {"databases": {"automation_updates": {"data_source_id": SOURCE}}}
        atomic_json(core.state_path(self.c, "notion-bootstrap.json"), registry)
        return registry

    def test_offline_self_test_and_template_export_need_no_config(self):
        with patch("work_context.notion.NotionClient.call", side_effect=AssertionError("Network forbidden")):
            code, result = self.run_cli("self-test", config=False)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["network_calls"], 0)
            code, result = self.run_cli("export-notion-templates", "--output", str(self.root / "Templates"), config=False)
            self.assertEqual(code, 0)
            self.assertEqual(len(result["files"]), 5)

    def test_repair_flag_regenerates_damaged_packet(self):
        code, first = self.run_cli("sync")
        self.assertEqual(code, 0)
        Path(first["packet_path"]).write_text("damaged")
        self.assertEqual(self.run_cli("sync")[0], 2)
        self.assertEqual(self.run_cli("sync", "--repair")[0], 0)

    def test_connection_check_uses_reader_and_explicit_registry(self):
        self.c["notion"]["page_ids"] = [PAGE]
        atomic_json(Path(self.config), self.c)
        registry = self.registry()
        with patch("work_context.cli.os.environ", {"NOTION_READ_TOKEN": "read-example", "NOTION_WRITE_TOKEN": "write-example"}), patch("work_context.notion_setup.connection_check", return_value={"status": "ready", "pages": []}) as check:
            self.assertEqual(self.run_cli("connection-check")[0], 0)
            self.assertEqual(check.call_args.args[1:], ([PAGE],))
            self.assertEqual(check.call_args.args[0]._token, "read-example")
            self.assertEqual(self.run_cli("connection-check", "--include-bootstrap")[0], 0)
            self.assertEqual(check.call_args.args[2], registry)

    def test_draft_metadata_is_normalized_and_hash_bound(self):
        self.run_cli("sync")
        code, result = self.run_cli("draft-update", "--title", "Synthetic", "--summary", "Synthetic outcome", "--classification", "Public", "--project-page-id", PAGE.replace("-", ""), "--work-item-page-id", DATABASE)
        self.assertEqual(code, 0)
        draft = read_json(Path(result["draft_path"]))
        self.assertEqual(draft["project_page_ids"], [PAGE])
        self.assertEqual(draft["work_item_page_ids"], [DATABASE])
        self.assertEqual(draft["classification"], "Public")
        self.assertEqual(draft["payload_hash"], digest({k: v for k, v in draft.items() if k != "payload_hash"}))

    def test_connection_check_access_loss_revokes_current_packet(self):
        self.c["notion"]["page_ids"] = [PAGE]
        atomic_json(Path(self.config), self.c)
        first = core.sync(self.c)
        with patch("work_context.notion_setup.connection_check", side_effect=BridgeError("NOTION_ACCESS", "No source access")):
            code, result = self.run_cli("connection-check")
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "NOTION_ACCESS")
        self.assertFalse(Path(first["packet_path"]).exists())
        self.assertEqual(core.status(self.c)["state"], "UNAVAILABLE")

    def test_schema_only_connection_failure_does_not_revoke_sources(self):
        self.c["notion"]["page_ids"] = [PAGE]
        atomic_json(Path(self.config), self.c)
        self.registry()
        first = core.sync(self.c)
        def check(_client, ids, registry=None):
            if registry is not None:
                raise BridgeError("NOTION_ACCESS", "No destination access")
            return {"status": "ready", "pages": [{"page_id": PAGE}]}
        with patch("work_context.notion_setup.connection_check", side_effect=check):
            self.assertEqual(self.run_cli("connection-check", "--include-bootstrap")[0], 2)
        self.assertTrue(Path(first["packet_path"]).exists())
        self.assertEqual(core.status(self.c)["state"], "FRESH")

    def test_view_apply_requires_exact_dry_plan_hash(self):
        self.registry()
        plan = {"action": "provision_views", "views": [{"name": "Example"}]}
        with patch("work_context.notion_setup.provision_views", side_effect=lambda *a, **k: {"status": "complete"} if k["apply"] else plan) as operation:
            code, result = self.run_cli("notion-views")
            self.assertEqual(code, 0)
            code, error = self.run_cli("notion-views", "--apply", "--reviewed-hash", "wrong")
            self.assertEqual(error["error"]["code"], "REVIEW_MISMATCH")
            self.assertFalse(any(call.kwargs["apply"] for call in operation.call_args_list))
            code, result = self.run_cli("notion-views", "--apply", "--reviewed-hash", digest(plan))
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "complete")

    def test_bootstrap_reconcile_applies_only_reviewed_candidate(self):
        plan = {"status": "verified", "database_id": DATABASE}
        with patch("work_context.notion_setup.reconcile_bootstrap", return_value=plan) as operation:
            args = ("notion-reconcile", "--parent-page", PAGE, "--database-id", DATABASE)
            self.assertEqual(self.run_cli(*args, "--apply", "--reviewed-hash", "wrong")[0], 2)
            self.assertFalse(operation.call_args.kwargs["apply"])
            self.assertEqual(self.run_cli(*args, "--apply", "--reviewed-hash", digest(plan))[0], 0)
            self.assertTrue(operation.call_args.kwargs["apply"])

    def test_update_reconciliation_cannot_use_another_destination(self):
        self.registry()
        with patch("work_context.notion_setup.reconcile_update", side_effect=AssertionError("Should not run")):
            code, result = self.run_cli("update-reconcile", "--draft", "unused.json", "--data-source-id", DATABASE, "--page-id", PAGE)
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "DESTINATION")


if __name__ == "__main__":
    unittest.main()
