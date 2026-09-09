"""Bounded Notion bridge. No token persistence, discovery, or automatic write retries.

The injected transport receives (method, /v1/path, JSON-or-None) and returns a
decoded object, or raises NotionHTTPError. Network requests use the same contract.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib import error, request
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from .common import BridgeError, atomic_json, digest, read_json

API_VERSION = "2026-03-11"
# v0.1 had identical database properties but older setup/publisher policy prose.
LEGACY_SCHEMA_HASH = "d731e0bb68d7709b1d2c215bfac44b58b02cbb755017dcee4c006e531a184adc"
MAX_RESPONSE_BYTES = 2_000_000
MAX_READ_RETRIES = 2
MAX_RETRY_DELAY = 15.0
_REAL_REQUEST_LOCK = threading.Lock()
_LAST_REAL_REQUEST = None


def _pace_real_request():
    """One process-wide start rate of at most two real HTTP requests per second."""
    global _LAST_REAL_REQUEST
    with _REAL_REQUEST_LOCK:
        now = time.monotonic()
        if _LAST_REAL_REQUEST is not None:
            delay = 0.5 - (now - _LAST_REAL_REQUEST)
            if delay > 0:
                time.sleep(delay)
        _LAST_REAL_REQUEST = time.monotonic()


def load_schema() -> dict:
    return json.loads(Path(__file__).with_name("notion_schema.json").read_text(encoding="utf-8"))


def _id(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise BridgeError("INVALID_NOTION_ID", "Expected a Notion UUID, not a URL or title.") from None


def _rich_text(value: str) -> list:
    return [{"type": "text", "text": {"content": value}}]


def _plain(items: list) -> str:
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise BridgeError("INVALID_RESPONSE", "Notion returned malformed rich text.")
    values = []
    for item in items:
        value = item.get("plain_text")
        if value is None:
            nested = item.get("text", {})
            value = nested.get("content", "") if isinstance(nested, dict) else None
        if not isinstance(value, str):
            raise BridgeError("INVALID_RESPONSE", "Notion returned malformed rich text.")
        values.append(value)
    return "".join(values)


class NotionHTTPError(Exception):
    """Sanitized transport failure; no remote message or response body is stored."""

    def __init__(self, status: int, retry_after=None):
        self.status = status
        self.retry_after = retry_after
        super().__init__(f"Notion HTTP {status}")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NotionClient:
    def __init__(self, token: str, api_version: str = API_VERSION, transport=None):
        self._token = token
        self.api_version = api_version
        self._injected_transport = transport is not None
        self._transport = transport if self._injected_transport else self._http

    def preflight(self):
        """Reject local configuration errors before writing an intent journal."""
        if not isinstance(self.api_version, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.api_version):
            raise BridgeError("INVALID_API_VERSION", "The Notion API version must be a YYYY-MM-DD date.")
        if self._injected_transport:
            return
        if not isinstance(self._token, str) or not self._token.strip():
            raise BridgeError("AUTH_REQUIRED", "Set the Notion token environment variable on the work computer.")
        if any(not 33 <= ord(character) <= 126 for character in self._token):
            raise BridgeError("INVALID_TOKEN", "The Notion token contains invalid characters; configure the environment variable again.")

    def _http(self, method, path, payload):
        self.preflight()
        encoded = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request("https://api.notion.com" + path, data=encoded, method=method, headers={
            "Authorization": "Bearer " + self._token,
            "Notion-Version": self.api_version,
            "Content-Type": "application/json",
        })
        try:
            _pace_real_request()
            with request.build_opener(_NoRedirect()).open(req, timeout=30) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise BridgeError("RESPONSE_TOO_LARGE", "Notion response exceeds the bounded read limit.")
            return json.loads(raw)
        except error.HTTPError as exc:
            raise NotionHTTPError(exc.code, exc.headers.get("Retry-After")) from None

    def call(self, method: str, path: str, payload=None, *, read=False) -> dict:
        parsed = urlsplit(path)
        ordinary = (not parsed.query and not (method == "GET" and parsed.path == "/v1/views")
                    and re.fullmatch(r"/v1/(?:pages|databases|data_sources|views)(?:/[a-zA-Z0-9_-]+){0,2}", path))
        view_list = False
        if method == "GET" and read and parsed.path == "/v1/views" and parsed.query:
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            params = dict(pairs)
            view_list = (len(pairs) == len(params) and set(params) <= {"database_id", "page_size", "start_cursor"}
                         and "database_id" in params and params.get("page_size", "100") == "100")
            if view_list:
                _id(params["database_id"])
                if "start_cursor" in params:
                    _id(params["start_cursor"])
        if parsed.scheme or parsed.netloc or parsed.fragment or not (ordinary or view_list):
            raise BridgeError("INVALID_ENDPOINT", "The Notion bridge refused an unsupported endpoint.")
        attempts = MAX_READ_RETRIES + 1 if read else 1
        for attempt in range(attempts):
            try:
                result = self._transport(method, path, payload)
                if not isinstance(result, dict):
                    raise BridgeError("INVALID_RESPONSE", "Notion returned a non-object response.")
                if result.get("object") == "error":
                    raise NotionHTTPError(result.get("status", 500), result.get("retry_after"))
                return result
            except NotionHTTPError as exc:
                if read and exc.status in (429, 529) and attempt < attempts - 1:
                    delay = self._retry_delay(exc.retry_after, attempt)
                    if delay is not None:
                        time.sleep(delay)
                        continue
                if exc.status in (401, 403, 404):
                    code, message = "NOTION_ACCESS", "Notion access is missing, revoked, or the requested object no longer exists."
                elif not read:
                    code, message = "WRITE_UNCERTAIN", "Notion write did not complete with a confirmed response; reconcile the journal before any retry."
                else:
                    code, message = "NOTION_HTTP", f"Notion read failed with HTTP {exc.status}; no source snapshot was accepted."
                raise BridgeError(code, message) from None
            except BridgeError:
                raise
            except Exception:
                code = "NOTION_TRANSPORT" if read else "WRITE_UNCERTAIN"
                raise BridgeError(code, "Notion request failed; connection details and remote content have been omitted.") from None
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_delay(value, attempt):
        if value is None:
            return float(2 ** attempt)
        try:
            delay = float(value)
        except (ValueError, TypeError):
            try:
                moment = parsedate_to_datetime(str(value))
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=timezone.utc)
                delay = (moment - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return None
        if not 0 <= delay <= MAX_RETRY_DELAY:
            return None
        return delay

    def fetch_pages(self, page_ids) -> list[dict]:
        """Read ONLY the explicit IDs; reject incomplete or concurrently edited pages."""
        ids = [_id(value) for value in page_ids]
        if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
            raise BridgeError("INVALID_ALLOWLIST", "Supply 1–100 unique explicit Notion page IDs.")
        pages = []
        for page_id in ids:
            before = self.call("GET", f"/v1/pages/{page_id}", read=True)
            title = _page_metadata(before, page_id)
            body = self.call("GET", f"/v1/pages/{page_id}/markdown", read=True)
            markdown = body.get("markdown")
            if (body.get("object") != "page_markdown" or _id(body.get("id")) != page_id
                    or body.get("truncated") is not False or body.get("unknown_block_ids") != []
                    or not isinstance(markdown, str) or re.search(r"<unknown\b", markdown, re.I)):
                raise BridgeError("INCOMPLETE_SOURCE", "Notion page content is truncated, inaccessible, or unsupported.")
            after = self.call("GET", f"/v1/pages/{page_id}", read=True)
            after_title = _page_metadata(after, page_id)
            if (before["last_edited_time"] != after["last_edited_time"] or title != after_title
                    or before.get("properties") != after.get("properties")
                    or before.get("parent") != after.get("parent")):
                raise BridgeError("SOURCE_CHANGED", "A Notion page changed during refresh; refresh again before compiling.")
            props = after.get("properties", {})
            row = {"id": page_id, "title": title, "markdown": markdown,
                   "last_edited_time": after["last_edited_time"], "url": after.get("url", "")}
            if "External ID" in props:
                row["external_id"] = _plain(props["External ID"].get("rich_text", []))
            for prop_name, field_name in (("Type", "requirement_type"), ("Status", "status"),
                                          ("Classification", "classification")):
                if prop_name in props:
                    selection = props[prop_name].get("select") or {}
                    if not isinstance(selection, dict) or not isinstance(selection.get("name", ""), str):
                        raise BridgeError("INVALID_SOURCE", "A Notion taxonomy selection is malformed.")
                    row[field_name] = selection.get("name", "")
            row.update(_source_links(props))
            pages.append(row)
        return pages


def _source_links(properties):
    """Parse declared links; never traverse them or silently drop malformed IDs."""
    links = {}
    if "Depends On IDs" in properties:
        try:
            values = properties["Depends On IDs"]["rich_text"]
            if not isinstance(values, list):
                raise ValueError
            raw = _plain(values)
            ids = [value for value in re.split(r"[,\s]+", raw.strip()) if value]
            if any(not re.fullmatch(r"(?:BR|AC|CON)-\d{3,}", value) for value in ids):
                raise ValueError
        except (KeyError, TypeError, AttributeError, ValueError):
            raise BridgeError("INVALID_SOURCE", "Depends On IDs must contain comma- or whitespace-separated BR-, AC-, or CON- numeric IDs.") from None
        links["depends_on_ids"] = list(dict.fromkeys(ids))
    if "Project" in properties:
        relation = properties["Project"]
        if not isinstance(relation, dict):
            raise BridgeError("INVALID_SOURCE", "The Notion Project relation is invalid.")
        if relation.get("has_more") is True:
            raise BridgeError("INCOMPLETE_SOURCE", "The Notion Project relation is incomplete; reduce the source's project links.")
        try:
            values = relation["relation"]
            if not isinstance(values, list):
                raise ValueError
            links["project_page_ids"] = list(dict.fromkeys(_id(value["id"]) for value in values))
        except (BridgeError, KeyError, TypeError, AttributeError, ValueError):
            raise BridgeError("INVALID_SOURCE", "The Notion Project relation contains an invalid page ID.") from None
    return links


def _page_metadata(page, page_id):
    if (page.get("object") != "page" or _id(page.get("id")) != page_id
            or page.get("archived", False) is not False or page.get("in_trash") is not False
            or not isinstance(page.get("last_edited_time"), str) or not page["last_edited_time"]):
        raise BridgeError("INVALID_SOURCE", "Notion source metadata is incomplete, archived, or invalid.")
    properties = page.get("properties", {})
    if not isinstance(properties, dict) or any(not isinstance(prop, dict) for prop in properties.values()):
        raise BridgeError("INVALID_SOURCE", "Notion page properties are malformed.")
    for prop in properties.values():
        if prop.get("type") == "title" and isinstance(prop.get("title"), list):
            return _plain(prop["title"])
    raise BridgeError("INVALID_SOURCE", "Notion page has no readable title metadata.")


@contextmanager
def _state_lock(path):
    """OS releases the lock on crash; the lock file itself is intentionally retained."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.with_suffix(path.suffix + ".lock").open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise BridgeError("STATE_BUSY", "Another Notion bridge process holds this state file.") from None
    try:
        yield
    finally:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _database_payload(spec, parent_page_id, known):
    properties = json.loads(json.dumps(spec["properties"]))
    for name, target in spec["relations"].items():
        properties[name] = {"relation": {"data_source_id": known.get(target, f"${{{target}.data_source_id}}"),
                                         "type": "single_property", "single_property": {}}}
    return {"parent": {"type": "page_id", "page_id": parent_page_id},
            "title": _rich_text(spec["name"]), "is_inline": False,
            "initial_data_source": {"properties": properties}}


def _bootstrap_state(state, parent_page_id=None, *, complete=False):
    """Validate journal structure before reading remote IDs or performing writes."""
    schema = load_schema()
    keys = [spec["key"] for spec in schema["databases"]]
    if (not isinstance(state, dict) or state.get("kind") != "notion_bootstrap"
            or state.get("schema_hash") not in (digest(schema), LEGACY_SCHEMA_HASH)
            or not isinstance(state.get("databases"), dict)):
        raise BridgeError("STATE_MISMATCH", "Bootstrap state belongs to an unsupported schema or is malformed.")
    parent = _id(state.get("parent_page_id"))
    if parent_page_id is not None and parent != _id(parent_page_id):
        raise BridgeError("STATE_MISMATCH", "Bootstrap state belongs to a different parent.")
    records = state["databases"]
    if set(records) != set(keys[:len(records)]):
        raise BridgeError("STATE_MISMATCH", "Bootstrap database records are not a valid completed prefix.")
    database_ids, source_ids = [], []
    for record in records.values():
        if not isinstance(record, dict):
            raise BridgeError("STATE_MISMATCH", "A bootstrap database record is malformed.")
        database_ids.append(_id(record.get("database_id")))
        source_ids.append(_id(record.get("data_source_id")))
    if len(set(database_ids)) != len(database_ids) or len(set(source_ids)) != len(source_ids):
        raise BridgeError("STATE_MISMATCH", "Bootstrap records reuse a database or data source ID.")
    pending = state.get("pending")
    if pending is not None:
        if (not isinstance(pending, dict) or len(records) >= len(keys)
                or pending.get("key") != keys[len(records)]
                or not isinstance(pending.get("payload_hash"), str)):
            raise BridgeError("STATE_MISMATCH", "Bootstrap pending operation is malformed.")
        spec = schema["databases"][len(records)]
        known = {key: _id(record["data_source_id"]) for key, record in records.items()}
        if digest(_database_payload(spec, parent, known)) != pending["payload_hash"]:
            raise BridgeError("STATE_MISMATCH", "The pending database payload differs from the recorded intent.")
    if complete and (pending is not None or len(records) != len(keys)):
        raise BridgeError("BOOTSTRAP_INCOMPLETE", "Finish or reconcile database setup before using this operation.")
    return schema


def _verify_database(client, spec, record, parent_page_id, known):
    """Verify identity, ownership, property types, selections and relation targets."""
    database_id, source_id = _id(record["database_id"]), _id(record["data_source_id"])
    database = client.call("GET", f"/v1/databases/{database_id}", read=True)
    if (database.get("object") != "database" or _id(database.get("id")) != database_id
            or database.get("archived", False) or database.get("in_trash", False)
            or _id(database.get("parent", {}).get("page_id")) != parent_page_id
            or _plain(database.get("title", [])) != spec["name"]
            or source_id not in [_id(source.get("id")) for source in database.get("data_sources", [])]):
        raise BridgeError("STATE_MISMATCH", "A registered database has changed identity, parent, title, or data source.")
    source = client.call("GET", f"/v1/data_sources/{source_id}", read=True)
    if (source.get("object") != "data_source" or _id(source.get("id")) != source_id
            or source.get("archived", False) or source.get("in_trash", False)
            or _id(source.get("parent", {}).get("database_id")) != database_id):
        raise BridgeError("STATE_MISMATCH", "A registered data source was moved, archived, or replaced.")
    expected = _database_payload(spec, parent_page_id, known)["initial_data_source"]["properties"]
    actual = source.get("properties")
    if not isinstance(actual, dict):
        raise BridgeError("SCHEMA_MISMATCH", "A registered data source has no readable properties.")
    for name, shape in expected.items():
        kind = next(iter(shape))
        prop = actual.get(name)
        if not isinstance(prop, dict) or prop.get("type") != kind or not isinstance(prop.get(kind), dict):
            raise BridgeError("SCHEMA_MISMATCH", f"The {spec['name']} property {name} is missing or has the wrong type.")
        if kind == "select":
            options = prop[kind].get("options")
            if not isinstance(options, list) or {entry.get("name") for entry in options if isinstance(entry, dict)} != {entry["name"] for entry in shape[kind]["options"]}:
                raise BridgeError("SCHEMA_MISMATCH", f"The {spec['name']} property {name} has different selection options.")
        if kind == "relation" and (_id(prop[kind].get("data_source_id")) != shape[kind]["data_source_id"]
                                    or prop[kind].get("type") != "single_property"):
            raise BridgeError("SCHEMA_MISMATCH", f"The {spec['name']} relation {name} targets a different data source or relation type.")
    return source


def bootstrap(client: NotionClient, parent_page_id: str, state_path, apply: bool = False) -> dict:
    """Plan or create a fresh taxonomy. state_path accepts str or pathlib.Path.

    A dry run is stable and makes no network calls or writes. A pending create
    requires explicit reconciliation: never delete the journal to force a retry.
    """
    parent_page_id = _id(parent_page_id)
    schema = load_schema()
    plan = {"action": "bootstrap", "parent_page_id": parent_page_id,
            "api_version": client.api_version, "schema_hash": digest(schema),
            "databases": [{"key": spec["key"], "schema": spec,
                           "payload": _database_payload(spec, parent_page_id, {})} for spec in schema["databases"]]}
    if not apply:
        return plan
    client.preflight()
    state_path = Path(state_path)
    with _state_lock(state_path):
        state = read_json(state_path) if state_path.exists() else {
            "kind": "notion_bootstrap", "schema_hash": plan["schema_hash"],
            "parent_page_id": parent_page_id, "databases": {}, "pending": None}
        _bootstrap_state(state, parent_page_id)
        if state.get("pending"):
            raise BridgeError("BOOTSTRAP_UNCERTAIN", "A previous database create is unconfirmed. Use notion-reconcile with its explicit database ID; no create was retried.")
        known = {}
        for spec in schema["databases"]:
            key = spec["key"]
            if key in state["databases"]:
                record = state["databases"][key]
                _verify_database(client, spec, record, parent_page_id, known)
                known[key] = _id(record["data_source_id"])
                continue
            payload = _database_payload(spec, parent_page_id, known)
            state["pending"] = {"key": key, "payload_hash": digest(payload)}
            atomic_json(state_path, state)
            result = client.call("POST", "/v1/databases", payload)
            sources = result.get("data_sources", [])
            if result.get("object") != "database" or len(sources) != 1:
                raise BridgeError("WRITE_UNCERTAIN", "Database creation returned an unexpected response. Use notion-reconcile with the created database ID.")
            record = {"database_id": _id(result.get("id")), "data_source_id": _id(sources[0].get("id"))}
            _verify_database(client, spec, record, parent_page_id, known)
            state["databases"][key] = record
            known[key] = record["data_source_id"]
            state["pending"] = None
            atomic_json(state_path, state)
        state["schema_hash"] = plan["schema_hash"]
        atomic_json(state_path, state)
        return {"action": "bootstrap", "status": "complete", "parent_page_id": parent_page_id,
                "schema_hash": plan["schema_hash"], "databases": state["databases"]}


def _update_payload(data_source_id, draft):
    required = ("external_id", "title", "markdown", "payload_hash")
    optional = {"classification", "project_page_ids", "work_item_page_ids"}
    if (not isinstance(draft, dict) or not set(required) <= set(draft) or set(draft) - set(required) - optional
            or any(not isinstance(draft.get(key), str) or not draft[key] for key in required)):
        raise BridgeError("INVALID_DRAFT", "Update draft requires external_id, title, markdown, payload_hash, and only supported optional metadata.")
    if len(draft["external_id"]) > 200 or len(draft["title"]) > 2000 or len(draft["markdown"].encode("utf-8")) > 100_000:
        raise BridgeError("INVALID_DRAFT", "Update draft exceeds the bounded publishing size.")
    if "classification" in draft and draft["classification"] not in ("Public", "Internal", "Confidential", "Restricted"):
        raise BridgeError("INVALID_DRAFT", "Update Classification must be a defined taxonomy classification.")
    relations = {}
    for key, name in (("project_page_ids", "Project"), ("work_item_page_ids", "Work Item")):
        if key in draft:
            values = draft[key]
            if not isinstance(values, list) or len(values) > 25:
                raise BridgeError("INVALID_DRAFT", "Update relations require at most 25 explicitly supplied page IDs.")
            ids = [_id(value) for value in values]
            if len(set(ids)) != len(ids):
                raise BridgeError("INVALID_DRAFT", "Update relations cannot repeat a page ID.")
            relations[name] = {"relation": [{"id": value} for value in ids]}
    expected = digest({key: value for key, value in draft.items() if key != "payload_hash"})
    if draft["payload_hash"] != expected:
        raise BridgeError("DRAFT_CHANGED", "Draft content does not match its payload hash; prepare and review it again.")
    payload = {"parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": {"Name": {"title": _rich_text(draft["title"])},
                           "External ID": {"rich_text": _rich_text(draft["external_id"])},
                           "Payload Hash": {"rich_text": _rich_text(expected)},
                           "Status": {"select": {"name": "Published"}}},
            "markdown": draft["markdown"]}
    payload["properties"].update(relations)
    if "classification" in draft:
        payload["properties"]["Classification"] = {"select": {"name": draft["classification"]}}
    return payload


def _find_update(client, data_source_id, external_id):
    result = client.call("POST", f"/v1/data_sources/{data_source_id}/query", {
        "filter": {"property": "External ID", "rich_text": {"equals": external_id}}, "page_size": 2}, read=True)
    if result.get("object") != "list" or not isinstance(result.get("results"), list):
        raise BridgeError("INVALID_RESPONSE", "Notion update lookup returned incomplete data.")
    if result.get("has_more") is not False or len(result["results"]) > 1:
        raise BridgeError("DUPLICATE_UPDATE", "Multiple updates use this External ID; resolve the conflict manually.")
    return result["results"][0] if result["results"] else None


def _verify_update_destination(client, data_source_id, payload):
    source = client.call("GET", f"/v1/data_sources/{data_source_id}", read=True)
    if (source.get("object") != "data_source" or _id(source.get("id")) != data_source_id
            or source.get("archived", False) or source.get("in_trash", False)
            or not isinstance(source.get("properties"), dict)):
        raise BridgeError("SCHEMA_MISMATCH", "Update destination is not an active readable data source.")
    for name, value in payload["properties"].items():
        kind = next(iter(value))
        prop = source["properties"].get(name)
        if not isinstance(prop, dict) or prop.get("type") != kind or not isinstance(prop.get(kind), dict):
            raise BridgeError("SCHEMA_MISMATCH", f"Update destination property {name} is missing or has the wrong type.")
        if kind == "select":
            options = prop[kind].get("options", [])
            if not isinstance(options, list) or value[kind]["name"] not in [entry.get("name") for entry in options if isinstance(entry, dict)]:
                raise BridgeError("SCHEMA_MISMATCH", f"Update destination property {name} lacks the requested selection.")
        if kind == "relation":
            target_source = _id(prop[kind].get("data_source_id"))
            for relation in value[kind]:
                page_id = relation["id"]
                page = client.call("GET", f"/v1/pages/{page_id}", read=True)
                if (page.get("object") != "page" or _id(page.get("id")) != page_id
                        or page.get("archived", False) or page.get("in_trash", False)
                        or _id(page.get("parent", {}).get("data_source_id")) != target_source):
                    raise BridgeError("RELATION_MISMATCH", "An explicitly selected update relation page is not in the destination relation's data source.")


def _verify_update_page(existing, data_source_id, draft, payload):
    if (existing.get("object") != "page" or existing.get("archived", False)
            or existing.get("in_trash", False)
            or _id(existing.get("parent", {}).get("data_source_id")) != data_source_id):
        raise BridgeError("UPDATE_CONFLICT", "The existing Notion update has the wrong parent or is not active.")
    props = existing.get("properties", {})
    if not isinstance(props, dict):
        raise BridgeError("UPDATE_CONFLICT", "The existing Notion update properties are unreadable.")
    for name, expected in payload["properties"].items():
        kind = next(iter(expected))
        prop = props.get(name)
        if not isinstance(prop, dict):
            raise BridgeError("UPDATE_CONFLICT", "The existing Notion update does not match this immutable payload.")
        if kind in ("title", "rich_text"):
            matches = _plain(prop.get(kind, [])) == _plain(expected[kind])
        elif kind == "select":
            matches = isinstance(prop.get(kind), dict) and prop[kind].get("name") == expected[kind]["name"]
        else:
            values = prop.get("relation")
            matches = (isinstance(values, list) and not prop.get("has_more", False)
                       and sorted(_id(value.get("id")) for value in values if isinstance(value, dict))
                       == sorted(value["id"] for value in expected[kind])
                       and all(isinstance(value, dict) for value in values))
        if not matches:
            raise BridgeError("UPDATE_CONFLICT", "The existing Notion update does not match this immutable payload.")
    return {"status": "published", "payload_hash": draft["payload_hash"],
            "page_id": _id(existing.get("id")), "url": existing.get("url", "")}


def publish_update(client: NotionClient, data_source_id: str, draft: dict, state_path, apply: bool = False) -> dict:
    """Insert an immutable update with durable uncertainty handling and deduplication.

    state_path accepts str or Path. A new call may reconcile a previous uncertain
    POST by External ID. If still absent, it stops instead of assuming absence
    proves the first write failed (Notion indexing may be delayed).
    """
    data_source_id = _id(data_source_id)
    payload = _update_payload(data_source_id, draft)
    plan = {"action": "publish_update", "data_source_id": data_source_id,
            "payload_hash": draft["payload_hash"], "payload": payload}
    if not apply:
        return plan
    client.preflight()
    state_path = Path(state_path)
    with _state_lock(state_path):
        state = read_json(state_path) if state_path.exists() else {"kind": "notion_outbox", "entries": {}}
        if state.get("kind") != "notion_outbox" or not isinstance(state.get("entries"), dict):
            raise BridgeError("STATE_MISMATCH", "Publisher state is not a valid Notion outbox.")
        key = digest({"data_source_id": data_source_id, "external_id": draft["external_id"]})
        previous = state["entries"].get(key)
        if previous is not None and (not isinstance(previous, dict) or previous.get("status") not in ("pending", "published")):
            raise BridgeError("STATE_MISMATCH", "The outbox entry is malformed or has an unsupported status.")
        if previous and previous.get("payload_hash") != draft["payload_hash"]:
            raise BridgeError("UPDATE_CONFLICT", "This External ID already belongs to a different payload; use a new ID for a correction.")
        if previous and previous.get("status") == "pending" and previous.get("payload") != payload:
            raise BridgeError("STATE_MISMATCH", "The pending outbox payload differs from the reviewed draft.")
        _verify_update_destination(client, data_source_id, payload)
        existing = _find_update(client, data_source_id, draft["external_id"])
        if existing:
            record = _verify_update_page(existing, data_source_id, draft, payload)
            if previous and previous.get("status") == "published" and _id(previous.get("page_id")) != record["page_id"]:
                raise BridgeError("UPDATE_CONFLICT", "The previously published update has been replaced by a different page.")
            state["entries"][key] = record
            atomic_json(state_path, state)
            return {"action": "publish_update", **record, "status": "already_published"}
        if previous:
            raise BridgeError("PUBLISH_UNCERTAIN", "A previous publish is not visible in Notion. Use update-reconcile with its explicit page ID; no write was retried.")
        state["entries"][key] = {"status": "pending", "payload_hash": draft["payload_hash"],
                                  "data_source_id": data_source_id, "external_id": draft["external_id"],
                                  "payload": payload}
        atomic_json(state_path, state)
        result = client.call("POST", "/v1/pages", payload)
        if result.get("object") != "page":
            raise BridgeError("WRITE_UNCERTAIN", "Publishing returned an unexpected response; reconcile the pending outbox.")
        record = _verify_update_page(result, data_source_id, draft, payload)
        state["entries"][key] = record
        atomic_json(state_path, state)
        return {"action": "publish_update", **record}
