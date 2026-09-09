"""Explicit local commands. Sync never invokes a model or executes project code."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .common import BridgeError, atomic_json, digest, project_lock, read_json, utc_now
from . import core


def notion_id(value: str) -> str:
    candidate = value.strip()
    if "://" in candidate:
        parsed = urlparse(candidate)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not any(host == x or host.endswith("." + x) for x in ("notion.so", "notion.site", "notion.com")):
            raise BridgeError("NOTION_ID", "Supply a Notion HTTPS page URL or UUID.")
        matches = re.findall(r"[a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", parsed.path)
        if not matches:
            raise BridgeError("NOTION_ID", "No page UUID found in the Notion URL.")
        candidate = matches[-1]
    try:
        return str(uuid.UUID(candidate))
    except ValueError as exc:
        raise BridgeError("NOTION_ID", "Supply a Notion page UUID or a URL containing one.") from exc


def parser():
    p = argparse.ArgumentParser(description="Portable Notion / Obsidian bridges. All output is JSON; no model calls.")
    p.add_argument("--config", type=Path, help="Project context/config.json")
    subs = p.add_subparsers(dest="command", required=True)
    init = subs.add_parser("init", help="Create the vault skeleton and non-secret local configuration")
    init.add_argument("--vault", type=Path, required=True)
    init.add_argument("--project", default="forecast-automation")
    init.add_argument("--project-id", default="PRJ-001")
    init.add_argument("--state-dir", type=Path)
    init.add_argument("--demo", action="store_true")
    subs.add_parser("doctor", help="Show local prerequisites without contacting Notion")
    subs.add_parser("status", help="Inspect source freshness and current local files")
    sync = subs.add_parser("sync", help="Capture configured sources and compile a packet")
    sync.add_argument("--task", default="TASK-001")
    packet = subs.add_parser("packet", help="Return the current handoff file path")
    packet.add_argument("--for", dest="target", choices=("claude", "cursor"), default="cursor")
    configure = subs.add_parser("configure-notion", help="Switch to explicitly selected live sources")
    configure.add_argument("--page-id", action="append", required=True)
    configure.add_argument("--reviewed-scope", action="store_true", help="Acknowledge that these work sources and data flows are approved")
    review = subs.add_parser("approve-source", help="Record a local acknowledgment of the exact captured source hash")
    review.add_argument("--reviewed-hash", required=True)
    review.add_argument("--actor", required=True)
    draft = subs.add_parser("draft-update", help="Prepare an update draft without sending it")
    draft.add_argument("--title", required=True)
    draft.add_argument("--summary", required=True)
    for name in ("notion-plan", "notion-bootstrap"):
        bootstrap = subs.add_parser(name, help="Plan or create the five Notion collections")
        bootstrap.add_argument("--parent-page", required=True)
        if name == "notion-bootstrap":
            bootstrap.add_argument("--apply", action="store_true")
            bootstrap.add_argument("--reviewed-hash")
    publish = subs.add_parser("publish", help="Plan or explicitly publish a prepared update")
    publish.add_argument("--draft", type=Path, required=True)
    publish.add_argument("--data-source-id", required=True)
    publish.add_argument("--apply", action="store_true")
    publish.add_argument("--reviewed-hash")
    return p


def handle(args):
    if args.command == "init":
        return core.initialize(args.vault, args.project, args.state_dir, args.demo, args.project_id)
    if args.command == "notion-plan":
        from .notion import NotionClient, bootstrap
        plan = bootstrap(NotionClient(""), notion_id(args.parent_page), Path("unused-plan-state.json"), apply=False)
        return {**plan, "reviewed_operation_hash": digest(plan), "model_calls": 0}
    if not args.config:
        raise BridgeError("CONFIG", "Supply --config PATH before the command. init prints the configuration path.")
    c = core.load_config(args.config)
    with project_lock(Path(c["state_dir"])):
        if args.command == "doctor":
            return core.doctor(c)
        if args.command == "status":
            health = core.status(c)
            if health["state"] != "NOT_SYNCED":
                core.render_status(c, health)
            return health
        if args.command == "sync":
            return core.sync(c, args.task)
        if args.command == "packet":
            return core.packet(c, args.target)
        if args.command == "configure-notion":
            if not args.reviewed_scope:
                raise BridgeError("SCOPE_REQUIRED", "Review the exact source pages and enterprise data flow, then supply --reviewed-scope on the work machine.")
            ids = list(dict.fromkeys(notion_id(x) for x in args.page_id))
            if len(ids) > 50:
                raise BridgeError("SCOPE_REQUIRED", "The pilot supports at most 50 explicit page IDs.")
            c["mode"] = "notion"
            c["notion"]["page_ids"] = ids
            c["notion"]["scope_acknowledged_at"] = utc_now()
            atomic_json(args.config, c)
            atomic_json(core.state_path(c, "source_review.json"), {"revoked": True, "reason": "Source scope changed"})
            core.record_failure(c, BridgeError("SCOPE_CHANGED", "Notion scope changed. Sync and review the captured content."))
            return {"mode": "notion", "page_ids": ids, "next": "Provision NOTION_READ_TOKEN locally, then run sync. No network request was made."}
        if args.command == "approve-source":
            receipt = core.acknowledge_source(c, args.reviewed_hash, args.actor)
            return {**receipt, "next": "Run sync to generate a packet with this review acknowledgment."}
        if args.command == "draft-update":
            return core.draft_update(c, args.title, args.summary)
        from .notion import NotionClient, bootstrap, publish_update
        client = NotionClient(os.environ.get(c["notion"]["write_token_env"], ""), api_version=c["notion"]["api_version"])
        if args.command == "notion-bootstrap":
            parent_id = notion_id(args.parent_page)
            state = core.state_path(c, "notion-bootstrap.json")
            plan = bootstrap(client, parent_id, state, apply=False)
            operation_hash = digest(plan)
            if not args.apply:
                return {**plan, "reviewed_operation_hash": operation_hash}
            if args.reviewed_hash != operation_hash:
                raise BridgeError("REVIEW_MISMATCH", "Run the dry plan and review its exact operation hash before applying this schema.")
            return bootstrap(client, parent_id, state, apply=True)
        if args.command == "publish":
            draft = read_json(args.draft)
            destination = notion_id(args.data_source_id)
            operation_hash = digest({"destination_data_source_id": destination, "draft": draft})
            state = core.state_path(c, "notion-outbox.json")
            if not args.apply:
                return {**publish_update(client, destination, draft, state, apply=False), "reviewed_operation_hash": operation_hash}
            if args.reviewed_hash != operation_hash:
                raise BridgeError("REVIEW_MISMATCH", "Review the exact update and destination using the dry plan before applying it.")
            registry = read_json(core.state_path(c, "notion-bootstrap.json"))
            # Only this kit's dedicated Updates collection is a publication target.
            registered = registry.get("databases", {}).get("automation_updates", {})
            allowed_id = registered.get("data_source_id")
            if allowed_id != destination:
                raise BridgeError("DESTINATION", "Publication is limited to the Automation Updates data source recorded by this project's bootstrap.")
            current = core.status(c)
            task_id = current.get("task_id", "TASK-001")
            fresh = core.sync(c, task_id)
            if f"Context bundle: {fresh['bundle_id']}\n" not in draft.get("markdown", ""):
                raise BridgeError("DRAFT_STALE", "Source, task, code, or review changed. Prepare and review a new update draft.")
            return publish_update(client, destination, draft, state, apply=True)
    raise BridgeError("COMMAND", "Unknown command.")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = handle(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BridgeError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Do not dump exceptions that may include HTTP bodies or secret environment values.
        print(json.dumps({"error": {"code": "LOCAL_FAILURE", "message": f"Local operation failed ({type(exc).__name__}); check configuration, file access, and source shapes."}}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
