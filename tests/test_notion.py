"""Contract tests with an in-memory Notion transport; no network or credentials."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID
from urllib.parse import parse_qs, urlsplit

from work_context.common import BridgeError, digest
from work_context.notion import NotionClient, NotionHTTPError, bootstrap, load_schema, publish_update


PARENT = str(UUID(int=1))
PAGE = str(UUID(int=2))
SOURCE = str(UUID(int=3))


def metadata(page_id=PAGE):
    return {"object": "page", "id": page_id, "in_trash": False,
            "last_edited_time": "2026-09-09T12:00:00Z", "url": "https://www.notion.so/" + page_id,
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "Mapping rule"}]},
                           "External ID": {"rich_text": [{"plain_text": "BR-001"}]},
                           "Type": {"select": {"name": "Rule"}},
                           "Status": {"select": {"name": "Approved"}},
                           "Classification": {"select": {"name": "Internal"}}}}


def markdown():
    return {"object": "page_markdown", "id": PAGE, "markdown": "Every code maps once.",
            "truncated": False, "unknown_block_ids": []}


def draft():
    value = {"external_id": "UPD-TASK-001", "title": "Mapping validation", "markdown": "Synthetic validation passed."}
    value["payload_hash"] = digest(value)
    return value


class Scripted:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, payload):
        self.calls.append((method, path, copy.deepcopy(payload)))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return copy.deepcopy(response)


class MemoryNotion:
    def __init__(self):
        self.calls = []
        self.databases = {}
        self.sources = {}
        self.pages = []
        self.views = []
        self.source_pages = {PARENT: metadata(PARENT)}
        spec = load_schema()["databases"][-1]
        self.sources[SOURCE] = {"object": "data_source", "id": SOURCE,
            "parent": {"type": "database_id", "database_id": PARENT},
            "properties": {name: {"id": "prop-" + str(index), "type": next(iter(shape)), **copy.deepcopy(shape)}
                           for index, (name, shape) in enumerate(spec["properties"].items())}}
        for name in ("Project", "Work Item"):
            self.sources[SOURCE]["properties"][name] = {"type": "relation", "relation": {"data_source_id": PARENT, "type": "single_property"}}
        self.uncertain_create = False
        self.uncertain_publish = False
        self.uncertain_view = False

    def __call__(self, method, path, payload):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if method == "POST" and path == "/v1/databases":
            database_id = str(UUID(int=100 + len(self.databases)))
            data_source_id = str(UUID(int=200 + len(self.databases)))
            result = {"object": "database", "id": database_id, "parent": payload["parent"],
                      "title": payload["title"],
                      "data_sources": [{"id": data_source_id}]}
            self.databases[database_id] = result
            self.sources[data_source_id] = {"object": "data_source", "id": data_source_id,
                "parent": {"type": "database_id", "database_id": database_id},
                "properties": {name: {"id": "prop-" + str(index), "type": next(iter(shape)), **copy.deepcopy(shape)}
                               for index, (name, shape) in enumerate(payload["initial_data_source"]["properties"].items())}}
            if self.uncertain_create:
                raise TimeoutError("sensitive request details")
            return copy.deepcopy(result)
        if method == "GET" and path.startswith("/v1/databases/"):
            return copy.deepcopy(self.databases[path.rsplit("/", 1)[1]])
        if method == "GET" and path.startswith("/v1/data_sources/"):
            return copy.deepcopy(self.sources[path.rsplit("/", 1)[1]])
        if method == "GET" and path.startswith("/v1/pages/"):
            page_id = path.rsplit("/", 1)[1]
            if page_id in self.source_pages:
                return copy.deepcopy(self.source_pages[page_id])
            return copy.deepcopy(next(page for page in self.pages if page["id"] == page_id))
        if method == "GET" and path.startswith("/v1/views?"):
            database_id = parse_qs(urlsplit(path).query)["database_id"][0]
            return {"object": "list", "has_more": False, "next_cursor": None,
                    "results": [{"object": "view", "id": view["id"]} for view in self.views
                                if view["parent"]["database_id"] == database_id]}
        if method == "GET" and path.startswith("/v1/views/"):
            return copy.deepcopy(next(view for view in self.views if view["id"] == path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/v1/views":
            result = {"object": "view", "id": str(UUID(int=400 + len(self.views))),
                "parent": {"type": "database_id", "database_id": payload["database_id"]},
                **{key: copy.deepcopy(value) for key, value in payload.items() if key != "database_id"}}
            self.views.append(result)
            if self.uncertain_view:
                raise TimeoutError("sensitive-view-request")
            return copy.deepcopy(result)
        if path.endswith("/query"):
            external_id = payload["filter"]["rich_text"]["equals"]
            pages = [page for page in self.pages if page["properties"]["External ID"]["rich_text"][0]["text"]["content"] == external_id]
            return {"object": "list", "results": copy.deepcopy(pages), "has_more": False}
        if method == "POST" and path == "/v1/pages":
            result = {"object": "page", "id": str(UUID(int=300 + len(self.pages))),
                      "url": "https://www.notion.so/example", "properties": payload["properties"], "parent": payload["parent"]}
            self.pages.append(copy.deepcopy(result))
            if self.uncertain_publish:
                raise TimeoutError("Bearer sensitive-token")
            return result
        raise AssertionError((method, path))


class NotionReadTests(unittest.TestCase):
    def test_same_timestamp_property_change_rejects_snapshot(self):
        for name, value in (("Status", {"select": {"name": "Draft"}}),
                            ("Classification", {"select": {"name": "Restricted"}}),
                            ("Depends On IDs", {"rich_text": [{"plain_text": "BR-010"}]}),
                            ("Project", {"relation": [{"id": PARENT}], "has_more": False})):
            with self.subTest(name=name):
                after = metadata()
                after["properties"][name] = value
                with self.assertRaises(BridgeError) as result:
                    NotionClient("", transport=Scripted([metadata(), markdown(), after])).fetch_pages([PAGE])
                self.assertEqual(result.exception.code, "SOURCE_CHANGED")

    def test_view_endpoint_allowlist_rejects_unscoped_and_external_queries(self):
        for path in ("/v1/views", "/v1/views?data_source_id=" + SOURCE, "/v1/views?database_id=" + PARENT + "&page_size=999",
                     "/v1/views?database_id=" + PARENT + "&database_id=" + PAGE,
                     "https://example.com/v1/views?database_id=" + PARENT,
                     "/v1/views?database_id=" + PARENT + "#token"):
            transport = Scripted([])
            with self.assertRaises(BridgeError):
                NotionClient("", transport=transport).call("GET", path, read=True)
            self.assertEqual(transport.calls, [])

    def test_dependency_ids_and_project_relation_are_exported_without_traversal(self):
        page = metadata()
        page["properties"]["Depends On IDs"] = {"rich_text": [{"plain_text": "BR-002, AC-010\nCON-001 BR-002"}]}
        page["properties"]["Project"] = {"relation": [{"id": PARENT}], "has_more": False}
        transport = Scripted([page, markdown(), page])
        result = NotionClient("", transport=transport).fetch_pages([PAGE])[0]
        self.assertEqual(result["depends_on_ids"], ["BR-002", "AC-010", "CON-001"])
        self.assertEqual(result["project_page_ids"], [PARENT])
        self.assertEqual(len(transport.calls), 3)

    def test_invalid_dependency_id_rejects_entire_source(self):
        for value in ("BR-001; AC-001", "BR-1", "ADR-001", "BR-001 https://example.com"):
            with self.subTest(value=value):
                page = metadata()
                page["properties"]["Depends On IDs"] = {"rich_text": [{"plain_text": value}]}
                transport = Scripted([page, markdown(), page])
                with self.assertRaises(BridgeError) as result:
                    NotionClient("", transport=transport).fetch_pages([PAGE])
                self.assertEqual(result.exception.code, "INVALID_SOURCE")

    def test_truncated_project_relation_is_rejected(self):
        page = metadata()
        page["properties"]["Project"] = {"relation": [{"id": PARENT}], "has_more": True}
        with self.assertRaises(BridgeError) as result:
            NotionClient("", transport=Scripted([page, markdown(), page])).fetch_pages([PAGE])
        self.assertEqual(result.exception.code, "INCOMPLETE_SOURCE")

    def test_real_http_clients_share_rate_limit(self):
        instant = [100.0]
        delays = []

        def sleep(seconds):
            delays.append(seconds)
            instant[0] += seconds

        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{}'
        with patch("work_context.notion.request.build_opener", return_value=opener), \
                patch("work_context.notion.time.monotonic", side_effect=lambda: instant[0]), \
                patch("work_context.notion.time.sleep", side_effect=sleep), \
                patch("work_context.notion._LAST_REAL_REQUEST", None):
            for _ in range(3):
                NotionClient("synthetic-token").call("GET", f"/v1/pages/{PAGE}", read=True)
        self.assertEqual(delays, [0.5, 0.5])
        self.assertEqual(opener.open.call_count, 3)

    def test_fetch_only_allowlisted_page_and_returns_taxonomy_metadata(self):
        transport = Scripted([metadata(), markdown(), metadata()])
        pages = NotionClient("fixture", transport=transport).fetch_pages([PAGE])
        self.assertEqual(pages[0]["external_id"], "BR-001")
        self.assertEqual(pages[0]["requirement_type"], "Rule")
        self.assertEqual(pages[0]["status"], "Approved")
        self.assertEqual(pages[0]["classification"], "Internal")
        self.assertEqual([call[1] for call in transport.calls], [f"/v1/pages/{PAGE}", f"/v1/pages/{PAGE}/markdown", f"/v1/pages/{PAGE}"])

    def test_incomplete_or_unknown_markdown_is_rejected(self):
        for overrides in ({"truncated": True}, {"unknown_block_ids": [PAGE]},
                          {"markdown": '<unknown url="private"/>'}, {"truncated": None}):
            with self.subTest(overrides=overrides):
                transport = Scripted([metadata(), {**markdown(), **overrides}])
                with self.assertRaises(BridgeError) as result:
                    NotionClient("fixture", transport=transport).fetch_pages([PAGE])
                self.assertEqual(result.exception.code, "INCOMPLETE_SOURCE")
                self.assertEqual(len(transport.calls), 2)

    def test_source_edit_during_read_is_rejected(self):
        changed = {**metadata(), "last_edited_time": "2026-09-09T12:00:01Z"}
        transport = Scripted([metadata(), markdown(), changed])
        with self.assertRaises(BridgeError) as result:
            NotionClient("fixture", transport=transport).fetch_pages([PAGE])
        self.assertEqual(result.exception.code, "SOURCE_CHANGED")

    def test_archived_revoked_and_duplicate_allowlist_fail_closed(self):
        for response in ({**metadata(), "in_trash": True}, NotionHTTPError(403)):
            with self.assertRaises(BridgeError):
                NotionClient("fixture", transport=Scripted([response])).fetch_pages([PAGE])
        transport = Scripted([])
        with self.assertRaises(BridgeError):
            NotionClient("fixture", transport=transport).fetch_pages([PAGE, PAGE])
        self.assertEqual(transport.calls, [])

    @patch("work_context.notion.time.sleep")
    def test_bounded_retry_honors_read_retry_after(self, sleep):
        transport = Scripted([NotionHTTPError(429, "0"), NotionHTTPError(529, "1"), metadata()])
        client = NotionClient("fixture", transport=transport)
        client.call("GET", f"/v1/pages/{PAGE}", read=True)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0, 1])

    @patch("work_context.notion.time.sleep")
    def test_large_retry_after_stops_without_retrying_early(self, sleep):
        transport = Scripted([NotionHTTPError(429, "60")])
        with self.assertRaises(BridgeError):
            NotionClient("fixture", transport=transport).call("GET", f"/v1/pages/{PAGE}", read=True)
        sleep.assert_not_called()
        self.assertEqual(len(transport.calls), 1)

    def test_transport_failure_does_not_expose_secret(self):
        transport = Scripted([RuntimeError("Bearer secret-value")])
        with self.assertRaises(BridgeError) as result:
            NotionClient("fixture", transport=transport).call("GET", f"/v1/pages/{PAGE}", read=True)
        self.assertNotIn("secret-value", str(result.exception))


class NotionWriteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / "state.json"
        self.transport = MemoryNotion()
        self.client = NotionClient("fixture", transport=self.transport)

    def test_dry_runs_are_stable_no_network_no_state_and_no_token(self):
        client = NotionClient("")
        first = bootstrap(client, PARENT, self.state)
        self.assertEqual(first, bootstrap(client, PARENT, self.state))
        self.assertEqual(len(first["databases"]), 5)
        result = publish_update(client, SOURCE, draft(), self.state)
        self.assertEqual(result["action"], "publish_update")
        self.assertFalse(self.state.exists())

    def test_missing_credentials_do_not_poison_write_journal(self):
        client = NotionClient("")
        with patch("work_context.notion.request.build_opener") as opener:
            for operation in (
                    lambda: bootstrap(client, PARENT, self.state, apply=True),
                    lambda: publish_update(client, SOURCE, draft(), self.state, apply=True)):
                with self.assertRaises(BridgeError) as result:
                    operation()
                self.assertEqual(result.exception.code, "AUTH_REQUIRED")
                self.assertFalse(self.state.exists())
            opener.assert_not_called()
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_injected_transport_requires_no_credentials(self):
        result = bootstrap(NotionClient("", transport=self.transport), PARENT, self.state, apply=True)
        self.assertEqual(result["status"], "complete")

    def test_invalid_header_configuration_does_not_poison_journal(self):
        for client in (NotionClient("has\nnewline"), NotionClient("nul\x00byte"), NotionClient("token", api_version="bad\nversion")):
            with self.assertRaises(BridgeError):
                bootstrap(client, PARENT, self.state, apply=True)
            self.assertFalse(self.state.exists())

    def test_bootstrap_creates_relations_and_resume_does_not_duplicate(self):
        result = bootstrap(self.client, PARENT, self.state, apply=True)
        self.assertEqual(result["status"], "complete")
        creates = [call for call in self.transport.calls if call[0] == "POST"]
        project_source = result["databases"]["projects"]["data_source_id"]
        self.assertEqual(creates[1][2]["initial_data_source"]["properties"]["Project"]["relation"]["data_source_id"], project_source)
        self.assertEqual(creates[1][2]["initial_data_source"]["properties"]["Project"]["relation"]["single_property"], {})
        bootstrap(self.client, PARENT, self.state, apply=True)
        self.assertEqual(len([call for call in self.transport.calls if call[0] == "POST"]), 5)
        self.assertFalse(any(call[0] == "PATCH" for call in self.transport.calls))

    def test_bootstrap_resume_rejects_schema_drift_without_writes(self):
        result = bootstrap(self.client, PARENT, self.state, apply=True)
        project_id = result["databases"]["projects"]["data_source_id"]
        self.transport.sources[project_id]["properties"]["Status"]["select"]["options"].append({"name": "Unexpected"})
        self.transport.calls.clear()
        with self.assertRaises(BridgeError) as result:
            bootstrap(self.client, PARENT, self.state, apply=True)
        self.assertEqual(result.exception.code, "SCHEMA_MISMATCH")
        self.assertTrue(all(call[0] == "GET" for call in self.transport.calls))

    def test_publish_hash_binds_classification_and_relations(self):
        value = {**draft(), "classification": "Internal", "project_page_ids": [PAGE], "work_item_page_ids": []}
        value["payload_hash"] = digest({key: item for key, item in value.items() if key != "payload_hash"})
        self.transport.source_pages[PAGE] = {**metadata(), "parent": {"data_source_id": PARENT}}
        result = publish_update(self.client, SOURCE, value, self.state, apply=True)
        self.assertEqual(result["status"], "published")
        props = self.transport.pages[0]["properties"]
        self.assertEqual(props["Classification"], {"select": {"name": "Internal"}})
        self.assertEqual(props["Project"], {"relation": [{"id": PAGE}]})
        before = len(self.transport.calls)
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, {**value, "classification": "Public"}, self.state, apply=True)
        self.assertEqual(result.exception.code, "DRAFT_CHANGED")
        self.assertEqual(len(self.transport.calls), before)

    def test_publish_rejects_relation_to_wrong_collection_before_journal(self):
        value = {**draft(), "project_page_ids": [PAGE]}
        value["payload_hash"] = digest({key: item for key, item in value.items() if key != "payload_hash"})
        self.transport.source_pages[PAGE] = {**metadata(), "parent": {"data_source_id": SOURCE}}
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, value, self.state, apply=True)
        self.assertEqual(result.exception.code, "RELATION_MISMATCH")
        self.assertFalse(self.state.exists())
        self.assertEqual(self.transport.pages, [])

    def test_publish_refuses_changed_destination_and_existing_properties(self):
        self.transport.sources[SOURCE]["properties"]["Payload Hash"]["type"] = "title"
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.assertEqual(result.exception.code, "SCHEMA_MISMATCH")
        self.assertFalse(self.state.exists())
        self.transport.sources[SOURCE]["properties"]["Payload Hash"]["type"] = "rich_text"
        publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.transport.pages[0]["properties"]["Name"] = {"title": [{"text": {"content": "Changed"}}]}
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.assertEqual(result.exception.code, "UPDATE_CONFLICT")

    def test_bootstrap_rejects_corrupt_pending_or_reused_ids_before_network(self):
        bootstrap(self.client, PARENT, self.state, apply=True)
        state = json.loads(self.state.read_text())
        state["databases"]["requirements"] = state["databases"]["projects"]
        self.state.write_text(json.dumps(state))
        self.transport.calls.clear()
        with self.assertRaises(BridgeError) as result:
            bootstrap(self.client, PARENT, self.state, apply=True)
        self.assertEqual(result.exception.code, "STATE_MISMATCH")
        self.assertEqual(self.transport.calls, [])

    def test_uncertain_bootstrap_keeps_journal_and_refuses_retry(self):
        self.transport.uncertain_create = True
        with self.assertRaises(BridgeError):
            bootstrap(self.client, PARENT, self.state, apply=True)
        self.assertEqual(json.loads(self.state.read_text())["pending"]["key"], "projects")
        with self.assertRaises(BridgeError) as result:
            bootstrap(self.client, PARENT, self.state, apply=True)
        self.assertEqual(result.exception.code, "BOOTSTRAP_UNCERTAIN")
        self.assertEqual(len(self.transport.databases), 1)

    def test_publish_deduplicates(self):
        first = publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        second = publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.assertEqual(first["status"], "published")
        self.assertEqual(second["status"], "already_published")
        self.assertEqual(first["page_id"], second["page_id"])
        self.assertEqual(len(self.transport.pages), 1)

    def test_uncertain_publish_reconciles_without_repeating_post(self):
        self.transport.uncertain_publish = True
        with self.assertRaises(BridgeError):
            publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        entries = json.loads(self.state.read_text())["entries"]
        self.assertEqual(next(iter(entries.values()))["status"], "pending")
        result = publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.assertEqual(result["status"], "already_published")
        self.assertEqual(len(self.transport.pages), 1)

    def test_uncertain_publish_absent_from_query_is_not_retried(self):
        self.transport.uncertain_publish = True
        with self.assertRaises(BridgeError):
            publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.transport.pages = []  # Eventual consistency or deleted destination.
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        self.assertEqual(result.exception.code, "PUBLISH_UNCERTAIN")
        self.assertEqual(len([call for call in self.transport.calls if call[1] == "/v1/pages"]), 1)

    def test_changed_external_id_payload_is_rejected(self):
        publish_update(self.client, SOURCE, draft(), self.state, apply=True)
        changed = {**draft(), "markdown": "Changed outcome."}
        changed["payload_hash"] = digest({key: value for key, value in changed.items() if key != "payload_hash"})
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, changed, self.state, apply=True)
        self.assertEqual(result.exception.code, "UPDATE_CONFLICT")
        self.assertEqual(len(self.transport.pages), 1)

    def test_bad_hash_rejected_before_network(self):
        with self.assertRaises(BridgeError) as result:
            publish_update(self.client, SOURCE, {**draft(), "markdown": "Changed"}, self.state, apply=True)
        self.assertEqual(result.exception.code, "DRAFT_CHANGED")
        self.assertEqual(self.transport.calls, [])

    def test_write_rate_limit_is_not_retried(self):
        transport = Scripted([NotionHTTPError(429, "0")])
        with self.assertRaises(BridgeError):
            NotionClient("fixture", transport=transport).call("POST", "/v1/pages", {})
        self.assertEqual(len(transport.calls), 1)

    def test_schema_has_exact_five_collections_and_three_requirement_types(self):
        schema = load_schema()
        self.assertEqual([entry["key"] for entry in schema["databases"]],
                         ["projects", "requirements", "work_items", "decisions", "automation_updates"])
        options = schema["databases"][1]["properties"]["Type"]["select"]["options"]
        self.assertEqual([option["name"] for option in options], ["Rule", "Acceptance", "Constraint"])


if __name__ == "__main__":
    unittest.main()
