"""Explicit Notion setup, connection diagnostics, and journal reconciliation.

No workspace search, implicit source traversal, schema overwrite or write retry.
Views are scoped to the five registered databases, with bounded pagination.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, unquote

from .common import BridgeError, atomic_json, atomic_text, contained, digest, read_json
from .notion import (
    _bootstrap_state, _database_payload, _id, _page_metadata, _state_lock,
    _update_payload, _verify_database, _verify_update_destination,
    _verify_update_page, load_schema,
)


def connection_check(client, page_ids, bootstrap_state=None) -> dict:
    """Read configured pages and registered schemas; never persist source content.

    page_ids may be empty when only testing a newly bootstrapped destination.
    bootstrap_state is the decoded bootstrap journal, or None for source-only use.
    Success verifies read access, not insert capability or company policy approval.
    """
    client.preflight()
    ids = [_id(value) for value in page_ids]
    if len(ids) > 100 or len(ids) != len(set(ids)):
        raise BridgeError("INVALID_ALLOWLIST", "Supply at most 100 unique explicit page IDs.")
    if not ids and bootstrap_state is None:
        raise BridgeError("INVALID_ALLOWLIST", "Configure source pages or a bootstrap state before checking the connection.")
    schema = _bootstrap_state(bootstrap_state, complete=True) if bootstrap_state is not None else None
    pages = client.fetch_pages(ids) if ids else []
    databases = []
    if schema:
        parent = _id(bootstrap_state["parent_page_id"])
        _page_metadata(client.call("GET", f"/v1/pages/{parent}", read=True), parent)
        known = {key: _id(record["data_source_id"]) for key, record in bootstrap_state["databases"].items()}
        for spec in schema["databases"]:
            record = bootstrap_state["databases"][spec["key"]]
            _verify_database(client, spec, record, parent, known)
            databases.append({"key": spec["key"], **record, "status": "verified"})
    return {"action": "connection_check", "status": "ready", "api_version": client.api_version,
            "pages": [{"page_id": page["id"], "status": "readable"} for page in pages],
            "databases": databases, "write_capability": "not_tested",
            "source_content_saved": False}


def reconcile_bootstrap(client, parent_page_id, state_path, database_id, apply=False) -> dict:
    """Adopt an explicitly identified pending database; never create or delete one."""
    parent, database_id = _id(parent_page_id), _id(database_id)
    state_path = Path(state_path)
    client.preflight()
    # Dry reconciliation reads its journal and remote candidate but writes nothing.
    def reconcile():
        state = read_json(state_path)
        schema = _bootstrap_state(state, parent)
        pending = state.get("pending")
        if not pending:
            raise BridgeError("NO_PENDING_OPERATION", "There is no pending database create to reconcile.")
        known = {key: _id(record["data_source_id"]) for key, record in state["databases"].items()}
        for spec in schema["databases"]:
            if spec["key"] in state["databases"]:
                _verify_database(client, spec, state["databases"][spec["key"]], parent, known)
        database = client.call("GET", f"/v1/databases/{database_id}", read=True)
        sources = database.get("data_sources")
        if not isinstance(sources, list) or len(sources) != 1:
            raise BridgeError("STATE_MISMATCH", "The pending database candidate must have exactly one data source.")
        record = {"database_id": database_id, "data_source_id": _id(sources[0].get("id"))}
        if (database_id in [_id(value["database_id"]) for value in state["databases"].values()]
                or record["data_source_id"] in known.values()):
            raise BridgeError("STATE_MISMATCH", "The candidate is already assigned to another collection.")
        spec = next(spec for spec in schema["databases"] if spec["key"] == pending["key"])
        _verify_database(client, spec, record, parent, known)
        result = {"action": "reconcile_bootstrap", "key": spec["key"], "parent_page_id": parent,
                  "payload_hash": pending["payload_hash"], **record, "status": "verified"}
        if apply:
            state["databases"][spec["key"]] = record
            state["pending"] = None
            state["schema_hash"] = digest(schema)
            atomic_json(state_path, state)
            result["status"] = "reconciled"
        return result
    if not apply:
        return reconcile()
    with _state_lock(state_path):
        return reconcile()


def reconcile_update(client, data_source_id, draft, state_path, page_id, apply=False) -> dict:
    """Settle an existing outbox entry using a page ID, without repeating POST."""
    source, page_id = _id(data_source_id), _id(page_id)
    payload = _update_payload(source, draft)
    state_path = Path(state_path)
    client.preflight()
    def reconcile():
        state = read_json(state_path)
        key = digest({"data_source_id": source, "external_id": draft["external_id"]})
        if not isinstance(state, dict) or state.get("kind") != "notion_outbox" or not isinstance(state.get("entries"), dict):
            raise BridgeError("STATE_MISMATCH", "Publisher state is not a valid Notion outbox.")
        previous = state["entries"].get(key)
        if not isinstance(previous, dict) or previous.get("payload_hash") != draft["payload_hash"]:
            raise BridgeError("STATE_MISMATCH", "There is no matching outbox intent to reconcile.")
        if previous.get("status") == "published" and _id(previous.get("page_id")) != page_id:
            raise BridgeError("UPDATE_CONFLICT", "The outbox already records a different published page.")
        if previous.get("status") not in ("pending", "published"):
            raise BridgeError("STATE_MISMATCH", "The outbox entry has an unsupported status.")
        if previous.get("status") == "pending" and previous.get("payload") != payload:
            raise BridgeError("STATE_MISMATCH", "The pending outbox payload differs from the reviewed draft.")
        _verify_update_destination(client, source, payload)
        existing = client.call("GET", f"/v1/pages/{page_id}", read=True)
        record = _verify_update_page(existing, source, draft, payload)
        if record["page_id"] != page_id:
            raise BridgeError("UPDATE_CONFLICT", "The retrieved page does not match the explicit candidate ID.")
        if apply:
            state["entries"][key] = record
            atomic_json(state_path, state)
        return {"action": "reconcile_update", **record, "status": "reconciled" if apply else "verified"}
    if not apply:
        return reconcile()
    with _state_lock(state_path):
        return reconcile()


def _view_payload(spec, view, record):
    payload = {"database_id": _id(record["database_id"]), "data_source_id": _id(record["data_source_id"]),
               "name": view["name"], "type": view["layout"]}
    if view.get("filter") is not None:
        payload["filter"] = view["filter"]
    if view.get("sorts"):
        payload["sorts"] = view["sorts"]
    return payload


def _list_views(client, database_id):
    views, seen, cursor = [], set(), None
    for _ in range(10):
        params = {"database_id": database_id, "page_size": "100"}
        if cursor:
            params["start_cursor"] = cursor
        page = client.call("GET", "/v1/views?" + urlencode(params), read=True)
        if (page.get("object") != "list" or not isinstance(page.get("results"), list)
                or len(page["results"]) > 100
                or page.get("request_status", {}).get("type", "complete") != "complete"):
            raise BridgeError("INCOMPLETE_VIEWS", "Notion returned an incomplete view listing; no missing view is assumed absent.")
        for item in page["results"]:
            if not isinstance(item, dict) or item.get("object") != "view":
                raise BridgeError("INCOMPLETE_VIEWS", "Notion returned an invalid view listing.")
            view_id = _id(item.get("id"))
            if view_id in seen:
                raise BridgeError("INCOMPLETE_VIEWS", "Notion view pagination repeated a view.")
            seen.add(view_id)
            # List results can contain partial objects, so verify full metadata.
            full = client.call("GET", f"/v1/views/{view_id}", read=True)
            if full.get("object") != "view" or _id(full.get("id")) != view_id:
                raise BridgeError("INCOMPLETE_VIEWS", "Notion returned mismatched view metadata.")
            views.append(full)
        if page.get("has_more") is False:
            return views
        if page.get("has_more") is not True:
            raise BridgeError("INCOMPLETE_VIEWS", "Notion view pagination has no completion marker.")
        next_cursor = _id(page.get("next_cursor"))
        if next_cursor == cursor:
            raise BridgeError("INCOMPLETE_VIEWS", "Notion view pagination did not advance.")
        cursor = next_cursor
    raise BridgeError("INCOMPLETE_VIEWS", "Database exceeds the bounded 1,000-view setup limit.")


def _view_matches(remote, payload, properties):
    # The API may render filter/sort property names as property IDs.
    names = {unquote(prop["id"]): name for name, prop in properties.items() if isinstance(prop, dict) and isinstance(prop.get("id"), str)}
    def normalize(value):
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: names.get(unquote(item), item) if key == "property" and isinstance(item, str) else normalize(item)
                    for key, item in value.items()}
        return value
    return (remote.get("object") == "view" and remote.get("name") == payload["name"]
            and remote.get("type") == payload["type"]
            and _id(remote.get("parent", {}).get("database_id")) == payload["database_id"]
            and _id(remote.get("data_source_id")) == payload["data_source_id"]
            and normalize(remote.get("filter") or None) == normalize(payload.get("filter") or None)
            and normalize(remote.get("sorts") or []) == normalize(payload.get("sorts") or []))


def provision_views(client, bootstrap_state, state_path, apply=False) -> dict:
    """Install the exact named views; retain default views and all human changes.

    Dry-run is offline. Applying verifies all registered schemas before any POST.
    Repeat calls adopt exactly matching views; uncertain missing views stop.
    """
    schema = _bootstrap_state(bootstrap_state, complete=True)
    records = bootstrap_state["databases"]
    entries = [{"key": spec["key"] + "/" + view["name"],
                "payload": _view_payload(spec, view, records[spec["key"]])}
               for spec in schema["databases"] for view in spec["views"]]
    plan = {"action": "provision_views", "bootstrap_hash": digest(records), "views": entries}
    if not apply:
        return plan
    client.preflight()
    state_path = Path(state_path)
    with _state_lock(state_path):
        state = read_json(state_path) if state_path.exists() else {
            "kind": "notion_views", "plan_hash": digest(plan), "views": {}}
        if (not isinstance(state, dict) or state.get("kind") != "notion_views"
                or state.get("plan_hash") != digest(plan) or not isinstance(state.get("views"), dict)
                or set(state["views"]) - {entry["key"] for entry in entries}):
            raise BridgeError("STATE_MISMATCH", "View state belongs to a different setup plan or is malformed.")
        for entry in entries:
            previous = state["views"].get(entry["key"])
            if previous is not None and (not isinstance(previous, dict)
                    or previous.get("payload_hash") != digest(entry["payload"])
                    or previous.get("status") not in ("pending", "created")):
                raise BridgeError("STATE_MISMATCH", "A view journal entry differs from its setup intent.")
        parent = _id(bootstrap_state["parent_page_id"])
        known = {key: _id(record["data_source_id"]) for key, record in records.items()}
        sources = {spec["key"]: _verify_database(client, spec, records[spec["key"]], parent, known)
                   for spec in schema["databases"]}
        listed = {key: _list_views(client, _id(record["database_id"])) for key, record in records.items()}
        for entry in entries:
            key, payload = entry["key"], entry["payload"]
            collection = key.split("/", 1)[0]
            matching = [view for view in listed[collection] if view.get("name") == payload["name"]]
            previous = state["views"].get(key)
            if len(matching) > 1:
                raise BridgeError("VIEW_CONFLICT", "Multiple views have a requested taxonomy name; no view was overwritten.")
            if matching:
                remote = matching[0]
                if not _view_matches(remote, payload, sources[collection]["properties"]):
                    raise BridgeError("VIEW_CONFLICT", "A named view has different filters, sorts, or ownership; no view was overwritten.")
                if previous and previous.get("status") == "created" and _id(previous.get("view_id")) != _id(remote.get("id")):
                    raise BridgeError("VIEW_CONFLICT", "A recorded view was replaced by a different view.")
            else:
                if previous:
                    raise BridgeError("VIEW_UNCERTAIN", "A recorded view is absent from Notion. Wait for indexing or inspect it; no create was retried.")
                state["views"][key] = {"status": "pending", "payload_hash": digest(payload)}
                atomic_json(state_path, state)
                created = client.call("POST", "/v1/views", payload)
                if created.get("object") != "view":
                    raise BridgeError("WRITE_UNCERTAIN", "View creation returned an unexpected response; its intent remains pending.")
                view_id = _id(created.get("id"))
                remote = client.call("GET", f"/v1/views/{view_id}", read=True)
                if _id(remote.get("id")) != view_id or not _view_matches(remote, payload, sources[collection]["properties"]):
                    raise BridgeError("WRITE_UNCERTAIN", "Created view could not be verified; its intent remains pending.")
            state["views"][key] = {"status": "created", "payload_hash": digest(payload), "view_id": _id(remote.get("id"))}
            atomic_json(state_path, state)
        return {"action": "provision_views", "status": "complete", "views": state["views"]}


def export_templates(output_dir) -> dict:
    """Export five editable Markdown starting points, preserving existing edits."""
    root = Path(output_dir).resolve()
    outputs = {}
    for spec in load_schema()["databases"]:
        lines = [f"# {spec['name']} template", "",
                 "Set the database properties in Notion before using this page.",
                 f"Canonical owner: {spec['canonical_owner']}.", ""]
        for section in spec["template_sections"]:
            lines.extend([f"## {section}", "", "[Complete this section.]", ""])
        outputs[contained(root, root / (spec["key"] + ".md"))] = "\n".join(lines)
    for path, body in outputs.items():
        if path.exists() and (not path.is_file() or path.read_text(encoding="utf-8") != body):
            raise BridgeError("TEMPLATE_EXISTS", "A template export has local edits; choose another output directory to preserve them.")
    for path, body in outputs.items():
        if not path.exists():
            atomic_text(path, body)
    return {"action": "export_templates", "status": "complete", "files": [str(path) for path in outputs],
            "native_templates": "Create database templates in the Notion app and paste these sections."}
