"""Explicit, model-free refresh and reviewable macOS scheduling artifacts."""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

from . import core
from .common import BridgeError, atomic_json, atomic_text, digest, read_json, utc_now


def _keychain_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.@ -]{1,120}", value) or value.startswith("-"):
        raise BridgeError("CREDENTIAL_REFERENCE", "Use a plain Keychain service/account name, never a credential value.")
    return value


def read_client(c, keychain_service=None, keychain_account=None):
    """Read a token in memory, without writing it or modifying the environment."""
    from .notion import NotionClient
    token = os.environ.get(c["notion"]["read_token_env"], "")
    if bool(keychain_service) != bool(keychain_account):
        raise BridgeError("CREDENTIAL_REFERENCE", "Supply both Keychain service and account names.")
    if not token and keychain_service:
        service, account = _keychain_name(keychain_service), _keychain_name(keychain_account)
        if sys.platform != "darwin":
            raise BridgeError("PLATFORM", "Keychain credential lookup is available only on macOS.")
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                capture_output=True, timeout=15, check=False,
            )
            if result.returncode != 0 or len(result.stdout) > 4096:
                raise BridgeError("AUTH_REQUIRED", "The configured Keychain item is unavailable; check it locally.")
            token = result.stdout.decode("ascii").rstrip("\r\n")
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
            raise BridgeError("AUTH_REQUIRED", "The local Keychain read failed; no credential output was recorded.") from exc
    return NotionClient(token, api_version=c["notion"]["api_version"])


def refresh(c, task_id="TASK-001", repair=False, keychain_service=None, keychain_account=None):
    """Capture locally and publish only reviewed reading context from the publisher.

    Caller holds the project lock. This function never acknowledges a source,
    runs a model, publishes to Notion, edits a human note, or upgrades code.
    """
    from .shared import invalidate_shared, publish_shared
    started = utc_now()
    diagnostic_path = core.state_path(c, "refresh-health.json")
    atomic_json(diagnostic_path, {"started_at": started, "state": "IN_PROGRESS", "model_calls": 0})
    try:
        client = read_client(c, keychain_service, keychain_account) if c["mode"] == "notion" else None
        health = core.sync(c, task_id, client=client, repair=repair)
        projection = {"status": "not_configured"}
        if c.get("shared"):
            if c["shared"]["member_id"] != c["shared"]["publisher_id"]:
                projection = {"status": "reader_only", "message": "This device captures local context; the designated publisher updates shared reading context."}
            elif health["review_status"] != "REVIEW_ACKNOWLEDGED_LOCAL":
                projection = invalidate_shared(c, "REVIEW_REQUIRED")
            else:
                projection = publish_shared(c)
        result = {**health, "action": "refresh", "shared": projection, "model_calls": 0,
                  "source_review_automated": False, "notion_writes": 0}
        atomic_json(diagnostic_path, {"started_at": started, "finished_at": utc_now(),
                    "state": health["state"], "review_status": health["review_status"], "shared": projection,
                    "model_calls": 0})
        return result
    except (BridgeError, OSError, ValueError, KeyError, TypeError) as exc:
        failure = exc if isinstance(exc, BridgeError) else BridgeError("REFRESH_FAILED", "Refresh failed locally; inspect the work profile and file access.")
        atomic_json(diagnostic_path, {"started_at": started, "finished_at": utc_now(),
                    "state": "FAILED", "error_code": failure.code, "model_calls": 0})
        # Also handles credential lookup failures that occur before core.sync.
        projection = None
        try:
            core.record_failure(c, failure)
            if c.get("shared") and c["shared"]["member_id"] == c["shared"]["publisher_id"]:
                projection = {"status": "invalidated", "reason_code": failure.code}
        except (BridgeError, OSError) as invalidation_error:
            projection = {"status": "invalidation_pending", "error_code": getattr(invalidation_error, "code", "LOCAL_STATE_IO")}
            failure = invalidation_error if isinstance(invalidation_error, BridgeError) else BridgeError("REFRESH_FAILED", "Context invalidation could not complete; inspect local and shared file access.")
        atomic_json(diagnostic_path, {"started_at": started, "finished_at": utc_now(),
                    "state": "FAILED", "error_code": failure.code, "shared": projection, "model_calls": 0})
        if failure is exc:
            raise
        raise failure from exc


def schedule_plan(c, config_path, task_id="TASK-001", interval=300, python_executable=None,
                  keychain_service=None, keychain_account=None):
    """Return a launchd plist and a hash-bound local export plan. No installation."""
    core.load_task(c, task_id)
    config = Path(config_path).expanduser().resolve()
    if core.load_config(config) != c:
        raise BridgeError("CONFIG", "Schedule must refer to the exact loaded configuration.")
    if isinstance(interval, bool) or not isinstance(interval, int) or not 60 <= interval <= 86400:
        raise BridgeError("SCHEDULE", "Refresh interval must be 60 to 86400 seconds.")
    if interval >= c["freshness_seconds"]:
        raise BridgeError("SCHEDULE", "Refresh interval must be shorter than the profile's freshness period.")
    python = Path(python_executable or sys.executable).expanduser().resolve()
    launcher = Path(__file__).resolve().parents[2] / "work-context.py"
    if not python.is_file() or not launcher.is_file():
        raise BridgeError("SCHEDULE", "Use the complete portable kit and an existing approved Python executable.")
    shared_root = Path(c["shared"]["vault_path"]).resolve() if c.get("shared") else None
    if shared_root and (python.is_relative_to(shared_root) or launcher.is_relative_to(shared_root)):
        raise BridgeError("SCHEDULE", "Keep the executable kit and runtime outside the shared Google Drive vault.")
    argv = [str(python), str(launcher), "--config", str(config), "refresh", "--task", task_id]
    if bool(keychain_service) != bool(keychain_account):
        raise BridgeError("CREDENTIAL_REFERENCE", "Supply both Keychain service and account names.")
    if keychain_service:
        argv += ["--keychain-service", _keychain_name(keychain_service), "--keychain-account", _keychain_name(keychain_account)]
    # One launchd identity per project prevents competing task schedules.
    label = "com.enterpriseconnector.refresh." + digest({"state": c["state_dir"]})[:16]
    plist = {"Label": label, "ProgramArguments": argv, "WorkingDirectory": c["project_path"],
             "StartInterval": interval, "RunAtLoad": True, "ProcessType": "Background",
             "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}
    plan = {"action": "export_refresh_schedule", "label": label, "task_id": task_id,
            "interval_seconds": interval, "plist": plist,
            "output_path": str(core.state_path(c, "launchd") / (label + ".plist")),
            "diagnostic_path": str(core.state_path(c, "refresh-health.json")),
            "config_hash": digest(c), "installed": False,
            "credential": "Keychain reference" if keychain_service else "NOTION_READ_TOKEN must be supplied by the launch environment"}
    return {**plan, "reviewed_operation_hash": digest(plan)}


def export_schedule(c, plan, reviewed_hash):
    expected = digest({key: value for key, value in plan.items() if key != "reviewed_operation_hash"})
    if reviewed_hash != expected or plan.get("reviewed_operation_hash") != expected or plan.get("config_hash") != digest(c):
        raise BridgeError("REVIEW_MISMATCH", "Review the exact schedule plan before exporting it.")
    if not re.fullmatch(r"com\.enterpriseconnector\.refresh\.[a-f0-9]{16}", plan.get("label", "")):
        raise BridgeError("SCHEDULE", "Invalid schedule label.")
    output = core.state_path(c, "launchd") / (plan["label"] + ".plist")
    if str(output) != plan["output_path"]:
        raise BridgeError("SCHEDULE", "The schedule output is outside this profile's local state.")
    # Local file export only. No launchctl, shell, scheduler or Keychain write.
    body = plistlib.dumps(plan["plist"], sort_keys=True).decode("utf-8")
    atomic_text(output, body)
    return {"action": "export_refresh_schedule", "plist_path": str(output), "label": plan["label"],
            "installed": False, "next": "Follow docs/SELF_UPDATE.md to install and start this reviewed LaunchAgent on the work Mac."}
