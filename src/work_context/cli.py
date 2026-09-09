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
    subs.add_parser("self-test", help="Exercise an isolated synthetic workflow and installed file integrity")
    templates = subs.add_parser("export-notion-templates", help="Export the five Notion Markdown starter templates locally")
    templates.add_argument("--output", type=Path, required=True)
    shared_init = subs.add_parser("init-shared", help="Create a shared reading vault and a separate local execution workspace")
    shared_init.add_argument("--shared-vault", type=Path, required=True)
    shared_init.add_argument("--local-workspace", type=Path, required=True)
    shared_init.add_argument("--project", default="forecast-automation")
    shared_init.add_argument("--project-id", default="PRJ-001")
    shared_init.add_argument("--member-id", choices=("luke", "boss"), default="luke")
    shared_init.add_argument("--publisher-id", choices=("luke", "boss"), default="luke")
    shared_init.add_argument("--state-dir", type=Path)
    shared_init.add_argument("--demo", action="store_true")
    subs.add_parser("shared-status", help="Validate the shared reading snapshot, its hashes and expiry")
    subs.add_parser("shared-publish", help="Publish reviewed reading context from the designated publisher")
    handover = subs.add_parser("shared-handover", help="Plan a coordinated change of the designated publisher")
    handover.add_argument("--publisher-id", choices=("luke", "boss"), required=True)
    handover.add_argument("--apply", action="store_true")
    handover.add_argument("--reviewed-hash")
    for name in ("refresh", "refresh-schedule"):
        refresh = subs.add_parser(name, help="Refresh local/shared reading context or export a Mac schedule")
        refresh.add_argument("--task", default="TASK-001")
        refresh.add_argument("--keychain-service")
        refresh.add_argument("--keychain-account")
        if name == "refresh":
            refresh.add_argument("--repair", action="store_true")
        else:
            refresh.add_argument("--interval", type=int, default=300)
            refresh.add_argument("--python", type=Path)
            refresh.add_argument("--apply", action="store_true")
            refresh.add_argument("--reviewed-hash")
    route_template = subs.add_parser("route-template", help="Print a model profile to verify on the work machine")
    route_template.add_argument("--workflow", choices=("claude", "cursor"), required=True)
    route_template.add_argument("--output", type=Path)
    route_init = subs.add_parser("route-init", help="Initialize a bounded model-stage ledger using verified model IDs")
    route_init.add_argument("--task", default="TASK-001")
    route_init.add_argument("--workflow", choices=("claude", "cursor"), required=True)
    route_init.add_argument("--models", type=Path)
    for name in ("route-next", "route-record", "route-resume"):
        route = subs.add_parser(name, help="Prepare the next model handoff or record human-reported evidence")
        route.add_argument("--run-id", required=True)
        if name == "route-record":
            route.add_argument("--outcome", choices=("plan-approved", "plan-rejected", "build-passed", "build-failed", "review-passed", "review-failed", "accepted", "rejected", "blocked"), required=True)
        if name in ("route-record", "route-resume"):
            route.add_argument("--evidence", type=Path, required=True)
            route.add_argument("--actor", required=True)
    init = subs.add_parser("init", help="Create the vault skeleton and non-secret local configuration")
    init.add_argument("--vault", type=Path, required=True)
    init.add_argument("--project", default="forecast-automation")
    init.add_argument("--project-id", default="PRJ-001")
    init.add_argument("--state-dir", type=Path)
    init.add_argument("--demo", action="store_true")
    subs.add_parser("doctor", help="Show local prerequisites without contacting Notion")
    subs.add_parser("status", help="Inspect source freshness and current local files")
    connection = subs.add_parser("connection-check", help="Check explicit Notion sources without saving their content")
    connection.add_argument("--include-bootstrap", action="store_true", help="Also verify registered schemas using the read credential")
    sync = subs.add_parser("sync", help="Capture configured sources and compile a packet")
    sync.add_argument("--task", default="TASK-001")
    sync.add_argument("--repair", action="store_true", help="Quarantine a damaged release and regenerate it from a fresh capture")
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
    draft.add_argument("--classification", default="Internal", choices=("Public", "Internal", "Confidential", "Restricted"))
    draft.add_argument("--project-page-id", action="append")
    draft.add_argument("--work-item-page-id", action="append")
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
    for name in ("notion-views", "notion-reconcile", "update-reconcile"):
        operation = subs.add_parser(name, help="Plan or apply explicit Notion setup/reconciliation")
        operation.add_argument("--apply", action="store_true")
        operation.add_argument("--reviewed-hash")
        if name == "notion-reconcile":
            operation.add_argument("--parent-page", required=True)
            operation.add_argument("--database-id", required=True)
        if name == "update-reconcile":
            operation.add_argument("--draft", type=Path, required=True)
            operation.add_argument("--data-source-id", required=True)
            operation.add_argument("--page-id", required=True)
    return p


def handle(args):
    if args.command == "init-shared":
        from .shared import initialize_shared
        return initialize_shared(args.shared_vault, args.local_workspace, args.project, args.project_id,
                                 args.member_id, args.publisher_id, args.state_dir, args.demo)
    if args.command == "route-template":
        from .routing import default_model_profile
        profile = default_model_profile(args.workflow)
        if args.output:
            output = args.output.expanduser().resolve()
            if output.exists():
                raise BridgeError("ROUTE_CONFIG", "Model profile already exists; preserve its local verification and choose a new output path.")
            atomic_json(output, profile)
            return {"profile_path": str(output), "profile": profile, "model_calls": 0}
        return profile
    if args.command == "self-test":
        from .readiness import run_self_test
        return run_self_test()
    if args.command == "export-notion-templates":
        from .notion_setup import export_templates
        return export_templates(args.output)
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
        if args.command in ("shared-status", "shared-publish", "shared-handover"):
            from .shared import shared_status, publish_shared, transfer_publisher
            if args.command == "shared-status":
                return shared_status(c)
            if args.command == "shared-publish":
                return publish_shared(c)
            return transfer_publisher(c, args.publisher_id, reviewed_hash=args.reviewed_hash, apply=args.apply)
        if args.command in ("refresh", "refresh-schedule"):
            from .refresh import refresh, schedule_plan, export_schedule
            if args.command == "refresh":
                return refresh(c, args.task, args.repair, args.keychain_service, args.keychain_account)
            plan = schedule_plan(c, args.config, args.task, args.interval, args.python, args.keychain_service, args.keychain_account)
            return export_schedule(c, plan, args.reviewed_hash) if args.apply else plan
        if args.command in ("route-init", "route-next", "route-record", "route-resume"):
            from .routing import initialize_route, next_route, record_route, resume_route
            if args.command == "route-init":
                return initialize_route(c, args.task, args.workflow, read_json(args.models) if args.models else None)
            if args.command == "route-next":
                return next_route(c, args.run_id)
            if args.command == "route-resume":
                return resume_route(c, args.run_id, args.evidence, args.actor)
            return record_route(c, args.run_id, args.outcome, args.evidence, args.actor)
        if args.command == "doctor":
            return core.doctor(c)
        if args.command == "status":
            health = core.status(c)
            if health["state"] != "NOT_SYNCED":
                core.render_status(c, health)
            return health
        if args.command == "sync":
            return core.sync(c, args.task, repair=args.repair)
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
            projects = list(dict.fromkeys(notion_id(x) for x in (args.project_page_id or [])))
            items = list(dict.fromkeys(notion_id(x) for x in (args.work_item_page_id or [])))
            return core.draft_update(c, args.title, args.summary, args.classification, projects, items)
        from .notion import NotionClient, bootstrap, publish_update
        from .notion_setup import connection_check, provision_views, reconcile_bootstrap, reconcile_update
        if args.command == "connection-check":
            reader = NotionClient(os.environ.get(c["notion"]["read_token_env"], ""), api_version=c["notion"]["api_version"])
            registry = read_json(core.state_path(c, "notion-bootstrap.json")) if args.include_bootstrap else None
            ids = c["notion"].get("page_ids", [])
            result = None
            if ids:
                try:
                    result = connection_check(reader, ids)
                except BridgeError as exc:
                    core.record_failure(c, exc)
                    raise
            if registry is not None:
                schemas = connection_check(reader, [], registry)
                return {**schemas, "pages": result["pages"] if result else []}
            if result is not None:
                return result
            raise BridgeError("INVALID_ALLOWLIST", "Configure source page IDs, or use --include-bootstrap to check registered schemas.")
        client = NotionClient(os.environ.get(c["notion"]["write_token_env"], ""), api_version=c["notion"]["api_version"])
        if args.command in ("notion-views", "notion-reconcile", "update-reconcile"):
            if args.command == "notion-views":
                registry = read_json(core.state_path(c, "notion-bootstrap.json"))
                def operation(apply):
                    return provision_views(client, registry, core.state_path(c, "notion-views.json"), apply=apply)
            elif args.command == "notion-reconcile":
                def operation(apply):
                    return reconcile_bootstrap(client, notion_id(args.parent_page), core.state_path(c, "notion-bootstrap.json"), notion_id(args.database_id), apply=apply)
            else:
                destination = notion_id(args.data_source_id)
                registry = read_json(core.state_path(c, "notion-bootstrap.json"))
                if registry.get("databases", {}).get("automation_updates", {}).get("data_source_id") != destination:
                    raise BridgeError("DESTINATION", "Reconciliation is limited to the registered Automation Updates data source.")
                draft = read_json(args.draft)
                def operation(apply):
                    return reconcile_update(client, destination, draft, core.state_path(c, "notion-outbox.json"), notion_id(args.page_id), apply=apply)
            plan = operation(False)
            operation_hash = digest(plan)
            if not args.apply:
                return {**plan, "reviewed_operation_hash": operation_hash}
            if args.reviewed_hash != operation_hash:
                raise BridgeError("REVIEW_MISMATCH", "Inspect the dry plan and supply its exact reviewed operation hash before applying.")
            return operation(True)
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
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Do not dump exceptions that may include HTTP bodies or secret environment values.
        print(json.dumps({"error": {"code": "LOCAL_FAILURE", "message": f"Local operation failed ({type(exc).__name__}); check configuration, file access, and source shapes."}}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
