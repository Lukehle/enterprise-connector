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
from uuid import UUID

from .common import BridgeError, atomic_json, digest, read_json

API_VERSION = "2026-03-11"
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
    return "".join(item.get("plain_text", item.get("text", {}).get("content", "")) for item in items)


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
        if not re.fullmatch(r"/v1/(?:pages|databases|data_sources)(?:/[a-zA-Z0-9_-]+){0,2}", path):
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
            if before["last_edited_time"] != after["last_edited_time"] or title != after_title:
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


def bootstrap(client: NotionClient, parent_page_id: str, state_path, apply: bool = False) -> dict:
    """Plan or create a fresh taxonomy. state_path accepts str or pathlib.Path.

    A dry run is stable and makes no network calls or writes. A pending create
    requires manual reconciliation: never delete the journal to force a retry.
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
        if any(state.get(key) != value for key, value in {
            "kind": "notion_bootstrap", "schema_hash": plan["schema_hash"], "parent_page_id": parent_page_id}.items()):
            raise BridgeError("STATE_MISMATCH", "Bootstrap state belongs to a different parent or schema.")
        if state.get("pending"):
            raise BridgeError("BOOTSTRAP_UNCERTAIN", "A previous database create is unconfirmed. Inspect Notion and reconcile the pending state manually; no create was retried.")
        known = {}
        for spec in schema["databases"]:
            key = spec["key"]
            if key in state["databases"]:
                record = state["databases"][key]
                database = client.call("GET", f"/v1/databases/{_id(record['database_id'])}", read=True)
                if (database.get("object") != "database" or database.get("archived", False)
                        or database.get("in_trash", False)
                        or _id(database.get("parent", {}).get("page_id")) != parent_page_id
                        or record["data_source_id"] not in [source.get("id") for source in database.get("data_sources", [])]):
                    raise BridgeError("STATE_MISMATCH", "A persisted database was moved, archived, or changed; no external schema was overwritten.")
                known[key] = _id(record["data_source_id"])
                continue
            payload = _database_payload(spec, parent_page_id, known)
            state["pending"] = {"key": key, "payload_hash": digest(payload)}
            atomic_json(state_path, state)
            result = client.call("POST", "/v1/databases", payload)
            sources = result.get("data_sources", [])
            if result.get("object") != "database" or len(sources) != 1:
                raise BridgeError("WRITE_UNCERTAIN", "Database creation returned an unexpected response. Reconcile the pending journal manually.")
            record = {"database_id": _id(result.get("id")), "data_source_id": _id(sources[0].get("id"))}
            state["databases"][key] = record
            known[key] = record["data_source_id"]
            state["pending"] = None
            atomic_json(state_path, state)
        return {"action": "bootstrap", "status": "complete", "parent_page_id": parent_page_id,
                "schema_hash": plan["schema_hash"], "databases": state["databases"]}


def _update_payload(data_source_id, draft):
    required = ("external_id", "title", "markdown", "payload_hash")
    if (not isinstance(draft, dict) or set(draft) != set(required)
            or any(not isinstance(draft.get(key), str) or not draft[key] for key in required)):
        raise BridgeError("INVALID_DRAFT", "Update draft requires only nonempty external_id, title, markdown, and payload_hash strings.")
    if len(draft["external_id"]) > 200 or len(draft["title"]) > 2000 or len(draft["markdown"].encode("utf-8")) > 100_000:
        raise BridgeError("INVALID_DRAFT", "Update draft exceeds the bounded publishing size.")
    expected = digest({key: draft[key] for key in required if key != "payload_hash"})
    if draft["payload_hash"] != expected:
        raise BridgeError("DRAFT_CHANGED", "Draft content does not match its payload hash; prepare and review it again.")
    return {"parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": {"Name": {"title": _rich_text(draft["title"])},
                           "External ID": {"rich_text": _rich_text(draft["external_id"])},
                           "Payload Hash": {"rich_text": _rich_text(expected)},
                           "Status": {"select": {"name": "Published"}}},
            "markdown": draft["markdown"]}


def _find_update(client, data_source_id, external_id):
    result = client.call("POST", f"/v1/data_sources/{data_source_id}/query", {
        "filter": {"property": "External ID", "rich_text": {"equals": external_id}}, "page_size": 2}, read=True)
    if result.get("object") != "list" or not isinstance(result.get("results"), list):
        raise BridgeError("INVALID_RESPONSE", "Notion update lookup returned incomplete data.")
    if result.get("has_more") is not False or len(result["results"]) > 1:
        raise BridgeError("DUPLICATE_UPDATE", "Multiple updates use this External ID; resolve the conflict manually.")
    return result["results"][0] if result["results"] else None


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
        if previous and previous.get("payload_hash") != draft["payload_hash"]:
            raise BridgeError("UPDATE_CONFLICT", "This External ID already belongs to a different payload; use a new ID for a correction.")
        existing = _find_update(client, data_source_id, draft["external_id"])
        if existing:
            props = existing.get("properties", {})
            remote_hash = _plain(props.get("Payload Hash", {}).get("rich_text", []))
            remote_id = _plain(props.get("External ID", {}).get("rich_text", []))
            if (existing.get("object") != "page" or existing.get("archived", False)
                    or existing.get("in_trash", False) or remote_hash != draft["payload_hash"]
                    or remote_id != draft["external_id"]):
                raise BridgeError("UPDATE_CONFLICT", "The existing Notion update does not match this immutable payload.")
            record = {"status": "published", "payload_hash": draft["payload_hash"],
                      "page_id": _id(existing.get("id")), "url": existing.get("url", "")}
            state["entries"][key] = record
            atomic_json(state_path, state)
            return {"action": "publish_update", **record, "status": "already_published"}
        if previous:
            raise BridgeError("PUBLISH_UNCERTAIN", "A previous publish is not visible in Notion. Reconcile it manually; no write was retried.")
        state["entries"][key] = {"status": "pending", "payload_hash": draft["payload_hash"],
                                  "data_source_id": data_source_id, "external_id": draft["external_id"],
                                  "payload": payload}
        atomic_json(state_path, state)
        result = client.call("POST", "/v1/pages", payload)
        if result.get("object") != "page":
            raise BridgeError("WRITE_UNCERTAIN", "Publishing returned an unexpected response; reconcile the pending outbox.")
        record = {"status": "published", "payload_hash": draft["payload_hash"],
                  "page_id": _id(result.get("id")), "url": result.get("url", "")}
        state["entries"][key] = record
        atomic_json(state_path, state)
        return {"action": "publish_update", **record}
