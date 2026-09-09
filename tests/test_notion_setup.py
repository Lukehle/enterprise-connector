"""Setup and recovery contract tests using realistic local Notion responses."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from work_context.common import BridgeError, digest
from work_context.notion import LEGACY_SCHEMA_HASH, NotionClient, bootstrap, publish_update
from work_context.notion_setup import (
    connection_check, export_templates, provision_views, reconcile_bootstrap,
    reconcile_update, _list_views,
)
from test_notion import MemoryNotion, PAGE, PARENT, SOURCE, Scripted, draft, markdown, metadata


class NotionSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bootstrap_path = self.root / "bootstrap.json"
        self.views_path = self.root / "views.json"
        self.outbox_path = self.root / "outbox.json"
        self.transport = MemoryNotion()
        self.client = NotionClient("", transport=self.transport)

    def setup_databases(self):
        bootstrap(self.client, PARENT, self.bootstrap_path, apply=True)
        self.transport.calls.clear()
        return json.loads(self.bootstrap_path.read_text())

    def assert_read_only(self):
        self.assertTrue(all(call[0] == "GET" or call[1].endswith("/query") for call in self.transport.calls))

    def test_connection_check_reads_only_allowlisted_pages_and_saves_no_body(self):
        transport = Scripted([metadata(), markdown(), metadata()])
        result = connection_check(NotionClient("", transport=transport), [PAGE])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["pages"], [{"page_id": PAGE, "status": "readable"}])
        self.assertFalse(result["source_content_saved"])
        self.assertNotIn("Every code maps once", json.dumps(result))
        self.assertEqual(len(transport.calls), 3)

    def test_connection_check_verifies_registered_schema_without_writes(self):
        state = self.setup_databases()
        before = self.bootstrap_path.read_bytes()
        result = connection_check(self.client, [], state)
        self.assertEqual(len(result["databases"]), 5)
        self.assertEqual(result["write_capability"], "not_tested")
        self.assert_read_only()
        self.assertEqual(self.bootstrap_path.read_bytes(), before)

    def test_connection_check_rejects_missing_relation_target(self):
        state = self.setup_databases()
        source = state["databases"]["requirements"]["data_source_id"]
        self.transport.sources[source]["properties"]["Project"]["relation"]["data_source_id"] = SOURCE
        with self.assertRaises(BridgeError) as caught:
            connection_check(self.client, [], state)
        self.assertEqual(caught.exception.code, "SCHEMA_MISMATCH")
        self.assert_read_only()

    def test_reconcile_timeout_database_adopts_verified_candidate_and_resumes(self):
        self.transport.uncertain_create = True
        with self.assertRaises(BridgeError):
            bootstrap(self.client, PARENT, self.bootstrap_path, apply=True)
        database_id = next(iter(self.transport.databases))
        self.transport.uncertain_create = False
        before = self.bootstrap_path.read_bytes()
        self.transport.calls.clear()
        preview = reconcile_bootstrap(self.client, PARENT, self.bootstrap_path, database_id)
        self.assertEqual(preview["status"], "verified")
        self.assertEqual(self.bootstrap_path.read_bytes(), before)
        self.assert_read_only()
        result = reconcile_bootstrap(self.client, PARENT, self.bootstrap_path, database_id, apply=True)
        self.assertEqual(result["status"], "reconciled")
        self.assert_read_only()
        bootstrap(self.client, PARENT, self.bootstrap_path, apply=True)
        self.assertEqual(len(self.transport.databases), 5)

    def test_reconcile_database_rejects_changed_schema_and_keeps_pending(self):
        self.transport.uncertain_create = True
        with self.assertRaises(BridgeError):
            bootstrap(self.client, PARENT, self.bootstrap_path, apply=True)
        database_id = next(iter(self.transport.databases))
        source_id = self.transport.databases[database_id]["data_sources"][0]["id"]
        del self.transport.sources[source_id]["properties"]["Classification"]
        before = self.bootstrap_path.read_bytes()
        with self.assertRaises(BridgeError) as caught:
            reconcile_bootstrap(self.client, PARENT, self.bootstrap_path, database_id, apply=True)
        self.assertEqual(caught.exception.code, "SCHEMA_MISMATCH")
        self.assertEqual(self.bootstrap_path.read_bytes(), before)

    def test_released_v01_journal_can_resume_after_live_schema_checks(self):
        state = self.setup_databases()
        state["schema_hash"] = LEGACY_SCHEMA_HASH
        self.bootstrap_path.write_text(json.dumps(state))
        result = bootstrap(self.client, PARENT, self.bootstrap_path, apply=True)
        self.assertEqual(result["status"], "complete")
        self.assertNotEqual(json.loads(self.bootstrap_path.read_text())["schema_hash"], LEGACY_SCHEMA_HASH)
        self.assert_read_only()

    def test_reconcile_explicit_update_without_indexed_query_or_new_post(self):
        self.transport.uncertain_publish = True
        with self.assertRaises(BridgeError):
            publish_update(self.client, SOURCE, draft(), self.outbox_path, apply=True)
        page_id = self.transport.pages[0]["id"]
        self.transport.calls.clear()
        before = self.outbox_path.read_bytes()
        preview = reconcile_update(self.client, SOURCE, draft(), self.outbox_path, page_id)
        self.assertEqual(preview["status"], "verified")
        self.assertEqual(self.outbox_path.read_bytes(), before)
        result = reconcile_update(self.client, SOURCE, draft(), self.outbox_path, page_id, apply=True)
        self.assertEqual(result["status"], "reconciled")
        self.assertEqual(len(self.transport.pages), 1)
        self.assertTrue(all(call[0] == "GET" for call in self.transport.calls))

    def test_update_reconciliation_rejects_wrong_parent_and_preserves_outbox(self):
        self.transport.uncertain_publish = True
        with self.assertRaises(BridgeError):
            publish_update(self.client, SOURCE, draft(), self.outbox_path, apply=True)
        page = self.transport.pages[0]
        page["parent"]["data_source_id"] = PARENT
        before = self.outbox_path.read_bytes()
        with self.assertRaises(BridgeError) as caught:
            reconcile_update(self.client, SOURCE, draft(), self.outbox_path, page["id"], apply=True)
        self.assertEqual(caught.exception.code, "UPDATE_CONFLICT")
        self.assertEqual(self.outbox_path.read_bytes(), before)

    def test_views_plan_offline_and_twelve_named_views_are_idempotent(self):
        state = self.setup_databases()
        preview = provision_views(NotionClient(""), state, self.views_path)
        self.assertEqual(len(preview["views"]), 12)
        self.assertFalse(self.views_path.exists())
        self.assertEqual(self.transport.calls, [])
        result = provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(self.transport.views), 12)
        self.transport.calls.clear()
        provision_views(self.client, state, self.views_path, apply=True)
        self.assert_read_only()
        self.assertEqual(len(self.transport.views), 12)
        filters = [view.get("filter") for view in self.transport.views]
        self.assertIn({"property": "Status", "select": {"equals": "Approved"}}, filters)
        self.assertEqual(self.transport.views[-1]["sorts"], [{"property": "Published At", "direction": "descending"}])

    def test_views_timeout_is_adopted_without_duplicate_post(self):
        state = self.setup_databases()
        self.transport.uncertain_view = True
        with self.assertRaises(BridgeError):
            provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(len(self.transport.views), 1)
        self.transport.uncertain_view = False
        result = provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(self.transport.views), 12)

    def test_views_missing_after_timeout_is_never_recreated(self):
        state = self.setup_databases()
        self.transport.uncertain_view = True
        with self.assertRaises(BridgeError):
            provision_views(self.client, state, self.views_path, apply=True)
        self.transport.views = []
        self.transport.calls.clear()
        with self.assertRaises(BridgeError) as caught:
            provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(caught.exception.code, "VIEW_UNCERTAIN")
        self.assert_read_only()

    def test_views_refuse_human_filter_edits_and_duplicate_names(self):
        state = self.setup_databases()
        provision_views(self.client, state, self.views_path, apply=True)
        original = copy.deepcopy(self.transport.views[0])
        self.transport.views[0]["filter"]["select"]["equals"] = "Archived"
        self.transport.calls.clear()
        with self.assertRaises(BridgeError) as caught:
            provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(caught.exception.code, "VIEW_CONFLICT")
        self.assert_read_only()
        self.transport.views[0] = original
        self.transport.views.append({**original, "id": PAGE})
        with self.assertRaises(BridgeError) as caught:
            provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(caught.exception.code, "VIEW_CONFLICT")
        self.assert_read_only()

    def test_views_accept_api_property_ids_in_filter_and_sort(self):
        state = self.setup_databases()
        provision_views(self.client, state, self.views_path, apply=True)
        for view in self.transport.views:
            properties = self.transport.sources[view["data_source_id"]]["properties"]
            if view.get("filter"):
                name = view["filter"]["property"]
                view["filter"]["property"] = properties[name]["id"]
            for item in view.get("sorts", []):
                item["property"] = properties[item["property"]]["id"]
        self.transport.calls.clear()
        provision_views(self.client, state, self.views_path, apply=True)
        self.assert_read_only()

    def test_view_pagination_requires_complete_results_and_advancing_cursor(self):
        for response in ({"object": "list", "results": [], "has_more": False, "request_status": {"type": "incomplete"}},
                         {"object": "list", "results": []},
                         {"object": "list", "results": ["malformed"], "has_more": False}):
            with self.subTest(response=response):
                with self.assertRaises(BridgeError) as caught:
                    _list_views(NotionClient("", transport=Scripted([response])), PARENT)
                self.assertEqual(caught.exception.code, "INCOMPLETE_VIEWS")
        page = {"object": "list", "results": [], "has_more": True, "next_cursor": PAGE}
        with self.assertRaises(BridgeError) as caught:
            _list_views(NotionClient("", transport=Scripted([page, page])), PARENT)
        self.assertEqual(caught.exception.code, "INCOMPLETE_VIEWS")

    def test_corrupt_view_state_fails_before_network(self):
        state = self.setup_databases()
        plan = provision_views(self.client, state, self.views_path)
        self.views_path.write_text(json.dumps({"kind": "notion_views", "plan_hash": digest(plan), "views": {"unexpected": {}}}))
        with self.assertRaises(BridgeError) as caught:
            provision_views(self.client, state, self.views_path, apply=True)
        self.assertEqual(caught.exception.code, "STATE_MISMATCH")
        self.assertEqual(self.transport.calls, [])

    def test_template_exports_preserve_local_edits_and_repeat_idempotently(self):
        output = self.root / "templates"
        result = export_templates(output)
        self.assertEqual(len(result["files"]), 5)
        self.assertEqual(result, export_templates(output))
        path = output / "requirements.md"
        self.assertIn("## Edge cases", path.read_text())
        path.write_text("My revised template")
        with self.assertRaises(BridgeError) as caught:
            export_templates(output)
        self.assertEqual(caught.exception.code, "TEMPLATE_EXISTS")
        self.assertEqual(path.read_text(), "My revised template")


if __name__ == "__main__":
    unittest.main()
