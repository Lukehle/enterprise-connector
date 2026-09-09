"""Offline installation checks using only disposable synthetic project data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile

from . import __version__, core
from .common import BridgeError


def verify_file_manifest(root: Path | None = None) -> dict:
    """Check release-listed bytes; a source checkout may have no manifest."""
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    path = root / "FILE_MANIFEST.json"
    if not path.exists() and not path.is_symlink():
        return {"status": "not_present", "detail": "Source checkout or package installation; use the release ZIP for manifest verification."}
    if path.is_symlink():
        raise BridgeError("KIT_INTEGRITY", "The release manifest must be a regular local file.")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not manifest or len(manifest) > 500:
            raise ValueError("Invalid manifest shape")
        for name, expected in manifest.items():
            if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                    or any(part in ("", ".", "..") for part in name.split("/"))
                    or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)):
                raise ValueError("Unsafe manifest member")
            target = root.joinpath(*PurePosixPath(name).parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError("Manifest path escapes kit")
            for candidate in (target, *target.parents):
                if candidate == root:
                    break
                info = candidate.lstat()
                if candidate.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ValueError("Linked manifest file")
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError("File missing or changed")
    except (OSError, ValueError, TypeError) as exc:
        raise BridgeError("KIT_INTEGRITY", "Release files do not match FILE_MANIFEST.json; restore a verified kit before use.") from exc
    return {"status": "verified", "files": len(manifest), "scope": "manifest-listed files"}


def run_self_test() -> dict:
    """Exercise core bridges in an owned temp vault with separate temp state.

    Accepts no user configuration: there is no route to a real vault or Notion.
    Synthetic vault and state are removed on success and failure.
    """
    if sys.version_info < (3, 11):
        raise BridgeError("PYTHON_VERSION", "Python 3.11 or newer is required.")
    manifest = verify_file_manifest()
    checks = []

    def require(condition: bool, label: str) -> None:
        if not condition:
            raise BridgeError("SELF_TEST", f"Synthetic installation check failed: {label}.")
        checks.append(label)

    with tempfile.TemporaryDirectory(prefix="enterprise-connector-self-test-") as temporary:
        base = Path(temporary)
        initialized = core.initialize(base / "Synthetic Work Vault", "installation-check", base / "Separate State", True)
        c = core.load_config(Path(initialized["config_path"]))
        require(c["mode"] == "fixture", "synthetic initialization")
        require(not Path(c["state_dir"]).is_relative_to(Path(c["vault_path"])), "state outside vault")
        first = core.sync(c, "TASK-001")
        require(first["state"] == "FRESH" and first["model_calls"] == 0, "offline source capture")
        core.acknowledge_source(c, first["source_hash"], "Synthetic installation reviewer")
        reviewed = core.sync(c, "TASK-001")
        require(reviewed["review_status"] == "REVIEW_ACKNOWLEDGED_LOCAL", "exact source review acknowledgment")
        for target in ("claude", "cursor"):
            packet = core.packet(c, target)
            body = Path(packet["path"]).read_text(encoding="utf-8")
            require("BR-001" in body and "AC-001" in body, f"{target} packet requirements")
        unchanged = core.sync(c, "TASK-001")
        require(unchanged["bundle_id"] == reviewed["bundle_id"], "unchanged capture reuses immutable packet")
        draft = core.draft_update(c, "Synthetic installation check", "Synthetic source and packet workflow completed; no work data was read.")
        require(Path(draft["draft_path"]).is_file() and "NOT_RUN" in draft["markdown"], "local outcome draft preserves verification limits")
        (Path(c["repo_path"]) / "src" / "synthetic_check.py").write_text("SYNTHETIC_VALUE = 1\n", encoding="utf-8")
        require(core.status(c)["state"] == "STALE", "code changes invalidate current packet")
        changed = core.sync(c, "TASK-001")
        require(changed["bundle_id"] != reviewed["bundle_id"] and changed["review_status"] == "REVIEW_ACKNOWLEDGED_LOCAL", "new code packet keeps source review")
    return {"status": "passed", "version": __version__, "python": sys.version.split()[0], "checks": checks,
            "file_manifest": manifest, "network_calls": 0, "model_calls": 0, "data": "synthetic only",
            "temporary_files": "removed", "live_notion": "not tested", "enterprise_authorization": "not assessed"}
