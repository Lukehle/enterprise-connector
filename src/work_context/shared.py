"""A human shared vault and a source-only mirror; runtime stays on each device.

Drive propagates files asynchronously. These checks provide local consistency,
not distributed locking, identity verification, or remote access revocation.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import core
from .common import BridgeError, atomic_json, atomic_text, contained, digest, read_json, utc_now

MEMBERS = ("luke", "boss")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HASH = re.compile(r"^[a-f0-9]{64}$")
PUBLICATION_ID = re.compile(r"^[a-f0-9]{24}$")
LOCAL_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|Volumes|private|tmp)/|\\\\[A-Za-z0-9])")
REGISTRY = "99 System/shared-vault.json"


def _read_bytes(path, limit=2_000_000):
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise BridgeError("SHARED_INTEGRITY", "Shared metadata or content is not a bounded regular file.")
        with path.open("rb") as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            raise BridgeError("SHARED_INTEGRITY", "Shared file exceeds its size budget.")
        return value
    except OSError as exc:
        raise BridgeError("SHARED_INTEGRITY", "A required shared file is missing or unreadable; let Drive finish synchronizing.") from exc


def _read_metadata(path):
    try:
        return json.loads(_read_bytes(path, 128_000).decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("SHARED_INTEGRITY", "Shared metadata is incomplete or invalid; let Drive finish synchronizing.") from exc


def _path(root, relative):
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts or ":" in str(relative):
        raise BridgeError("SHARED_PATH", "Shared destinations must be relative paths within their generated folder.")
    path = Path(root) / relative
    # Generated destinations never traverse links, including links that stay
    # inside the vault. A linked directory can be separately cloud-synced.
    current = path
    while current != Path(root).parent:
        if current.is_symlink():
            raise BridgeError("SHARED_PATH", "Shared bridge destinations cannot use symbolic links.")
        if current == Path(root):
            break
        current = current.parent
    return contained(Path(root), path)


def _new_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except FileExistsError:
        if not path.is_file():
            raise BridgeError("SHARED_PATH", "An existing scaffold destination is not a regular file.")


def _registry(root):
    value = _read_metadata(_path(root, REGISTRY))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise BridgeError("SHARED_CONFIG", "Unsupported shared vault registry.")
    try:
        uuid.UUID(value["vault_id"])
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise BridgeError("SHARED_CONFIG", "Shared vault needs a stable UUID identity.") from exc
    if value.get("members") != list(MEMBERS) or not isinstance(value.get("projects"), dict):
        raise BridgeError("SHARED_CONFIG", "Shared vault members or project registry is invalid.")
    seen = set()
    for slug, project in value["projects"].items():
        if not isinstance(slug, str) or not SLUG.fullmatch(slug) or not isinstance(project, dict):
            raise BridgeError("SHARED_CONFIG", "Invalid shared project entry.")
        if not isinstance(project.get("project_id"), str) or not re.fullmatch(r"PRJ-\d{3,}", project["project_id"]) or project["project_id"] in seen:
            raise BridgeError("SHARED_CONFIG", "Shared project IDs must be unique and stable.")
        seen.add(project["project_id"])
        if project.get("publisher_id") not in MEMBERS or type(project.get("publisher_epoch")) is not int or project["publisher_epoch"] < 1:
            raise BridgeError("SHARED_CONFIG", "Invalid shared publisher assignment.")
        if project.get("project_relative") != f"10 Projects/{slug}":
            raise BridgeError("SHARED_CONFIG", "Shared project location must follow the relative taxonomy.")
    return value


def initialize_shared(shared_vault, local_workspace, project_slug, project_id="PRJ-001", member_id="luke", publisher_id="luke", state_dir=None, demo=False):
    """Scaffold missing shared notes and a separately configured local project."""
    if member_id not in MEMBERS or publisher_id not in MEMBERS:
        raise BridgeError("SHARED_MEMBER", "Use member IDs luke or boss.")
    if not isinstance(project_slug, str) or not SLUG.fullmatch(project_slug) or not isinstance(project_id, str) or not re.fullmatch(r"PRJ-\d{3,}", project_id):
        raise BridgeError("SHARED_CONFIG", "Use a lowercase project slug and a stable PRJ-001 style ID.")
    shared = Path(shared_vault).expanduser().resolve()
    local = Path(local_workspace).expanduser().resolve()
    state = (Path(state_dir).expanduser().resolve() if state_dir is not None else core.default_state_dir(project_slug, local).resolve())
    for first, second in ((shared, local), (shared, state), (local, state)):
        if first.is_relative_to(second) or second.is_relative_to(first):
            raise BridgeError("SHARED_LOCATION", "Shared vault, local workspace, and runtime state must be separate non-overlapping directories.")
    registry_path = _path(shared, REGISTRY)
    registry = _registry(shared) if registry_path.exists() else {"schema_version": 1, "vault_id": str(uuid.uuid4()), "members": list(MEMBERS), "projects": {}}
    project = registry["projects"].get(project_slug)
    if project and project["project_id"] != project_id:
        raise BridgeError("SHARED_CONFIG", "This shared project already has a different stable ID.")
    if any(p["project_id"] == project_id for s, p in registry["projects"].items() if s != project_slug):
        raise BridgeError("SHARED_CONFIG", "That project ID is already allocated. Reserve another ID in the ID Register.")
    if not project and registry_path.exists() and member_id != publisher_id:
        raise BridgeError("SHARED_PUBLISHER", "The designated publisher must register a new project before other members join.")
    relative = f"10 Projects/{project_slug}"
    project = project or {"project_id": project_id, "project_relative": relative, "publisher_id": publisher_id, "publisher_epoch": 1}
    directories = ["01 Inbox/luke", "01 Inbox/boss", f"02 Meetings/{datetime.now(timezone.utc).year}", "20 Playbooks", "30 Reference", "90 Archive", "_templates", "99 System",
                   *[f"{relative}/{part}" for part in ("00 Overview", "10 Notes/luke", "10 Notes/boss", "20 Proposals", "30 Handoffs", "40 Published")]]
    files = _scaffold_files(relative, project_id)
    for item in [*directories, *files]:
        _path(shared, item)
    # Local initialization precedes registry publication, so invalid local
    # project names/state cannot leave a newly advertised shared project.
    result = core.initialize(local, project_slug, state, demo, project_id)
    config_path = Path(result["config_path"])
    config = core.load_config(config_path)
    if config["project_id"] != project_id or config["project_slug"] != project_slug or Path(config["state_dir"]).resolve() != state:
        raise BridgeError("SHARED_BINDING", "The existing local project's ID, slug, or runtime state does not match the requested shared binding. Use its original identity or initialize a separate local project.")
    binding = {"vault_path": str(shared), "vault_id": registry["vault_id"], "project_relative": relative, "member_id": member_id,
               "publisher_id": project["publisher_id"], "publisher_epoch": project["publisher_epoch"]}
    existing_binding = config.get("shared")
    if existing_binding and any(existing_binding.get(k) != binding[k] for k in ("vault_path", "vault_id", "project_relative", "member_id")):
        raise BridgeError("SHARED_BINDING", "This local project is already bound to a different shared vault or member.")
    for directory in directories:
        _path(shared, directory).mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        _new_text(_path(shared, name), body)
    if project_slug not in registry["projects"]:
        registry["projects"][project_slug] = project
        # Registry is generated metadata, maintained only by the agreed writer.
        # An already registered project is never rewritten on a scaffold rerun.
        atomic_json(registry_path, registry)
    config["shared"] = binding
    atomic_json(config_path, config)
    return {**result, "shared_vault": str(shared), "vault_id": registry["vault_id"], "member_id": member_id, "publisher_id": project["publisher_id"], "publisher_epoch": project["publisher_epoch"]}


def _scaffold_files(relative, project_id):
    note = "---\ntype: note\nstatus: working\nowner: luke\ncreated: YYYY-MM-DD\nproject_id: PRJ-001\nclassification: Internal\nrelated_ids: []\nnotion_url: null\n---\n# Note title\n\n## Observation\n\n## Next action\n\n## Promoted to / outcome\n"
    return {
        "00 Home/Home.md": f"# Work Together\n\n- [[00 Home/Working Agreement|Working agreement]]\n- [[00 Home/People|Roles]]\n- [[00 Home/ID Register|ID register]]\n- [[{relative}/00 Overview/Project|{project_id} project]]\n- [[{relative}/40 Published/README|Published Notion context]]\n\nAdd new project links here manually. Scaffold reruns preserve this page.\n",
        "00 Home/Working Agreement.md": "# Working agreement\n\nNotion owns approved business requirements, priorities, decisions, and acceptance. This vault owns working notes, meeting records, and reviewed playbooks. Finance Git in company Google Drive owns code, task contracts, and technical decisions. Keep that repository location separate from this notes vault; each Mac uses its own local execution checkout. No finance GitHub workflow is required.\n\nLuke is the initial registry allocator and generated-context publisher; Boss reviews business meaning. One named editor owns each shared note at a time. Capture in your own member folder and wait for Drive to finish syncing before handing a note over. Resolve conflict copies by comparison; do not silently discard either edit.\n\nHuman promotion is explicit: proposal in the vault, decision and approval in Notion, then a link back to the canonical Notion page. Generated context is a read-only mirror, never a second editable requirements source.\n\nNever put passwords, API tokens, customer extracts, Git repositories, local packet folders, or agent session logs in this vault. Use the approved company Drive location and its membership policy.\n",
        "00 Home/People.md": "# People\n\n| Member ID | Role | Owns |\n|---|---|---|\n| luke | Implementation owner; initial publisher | Local workspaces, technical proposals, generated mirror |\n| boss | Business owner/reviewer | Priority, business rules, acceptance, Notion approvals |\n\nThese IDs are coordination labels, not authenticated identities. Record real names/contact details in company systems if needed. Each project has one publisher and an increasing handover epoch in the shared registry.\n",
        "00 Home/ID Register.md": f"# ID Register\n\nRegistry allocator: luke. Reserve IDs before creating canonical records; do not allocate concurrently.\n\n| ID | Slug / title | State |\n|---|---|---|\n| {project_id} | {relative.split('/')[-1]} | reserved |\n\nPRJ IDs are unique across this vault. BR, AC, CON, BD, and PB IDs are monotonically allocated in their canonical registers and never reused; record subsequent allocations here or link to the Notion register. TASK IDs are project-scoped: always cite PRJ-001/TASK-001. Note filenames use date + topic + member, avoiding a shared counter. Scaffold adds machine registry entries but does not rewrite this human register.\n",
        "01 Inbox/README.md": "# Inbox\n\nCapture `YYYY-MM-DD--topic--member.md` under your member ID. Triage each workday: move to project notes, draft a proposal, turn an action into a Notion Work Item, or archive. An inbox note is never automatically an approved requirement.\n",
        "02 Meetings/README.md": "# Meetings\n\nUse `YYYY/YYYY-MM-DD--topic--scribe.md`. Assign one scribe. Capture agenda, observations, decisions proposed, and action links. Final approved decisions and actions live in Notion; retain this contemporaneous record and add their stable IDs.\n",
        f"{relative}/00 Overview/Project.md": f"---\ntype: project\nproject_id: {project_id}\nstatus: active\nclassification: Internal\nnotion_url: null\n---\n# {project_id}\n\n## Purpose\n\n## Canonical Notion links\n\nProjects row, approved requirements view, Work Items view, and Decisions view.\n\n## Finance repository\n\nLink to the company Drive repository through the Notion Projects row. Record its relative location, repository form, default branch and Git transfer owner there. Keep Mac filesystem paths local.\n\n## Working links\n\n- [[{relative}/40 Published/README|Published context usage]]\n\n## Ownership and review cadence\n\nBusiness owner: boss. Implementation owner: luke. Review proposals together weekly; update Notion before refreshing context.\n",
        f"{relative}/10 Notes/README.md": "# Working notes\n\nUse your member folder and date-topic-member filenames. Link related PRJ/TASK/BR/AC IDs. Notes are excluded from model context until explicitly promoted and reviewed.\n",
        f"{relative}/20 Proposals/README.md": "# Proposals\n\nUse `YYYY-MM-DD--proposal--member.md`. States: draft → in-review → accepted/rejected. Accepted means the proposal has an outcome; it becomes a business requirement only after the accountable owner updates and approves its canonical Notion record. Add that record's URL and ID here.\n",
        f"{relative}/30 Handoffs/README.md": "# Handoffs\n\nUse `YYYY-MM-DD--TASK-001--member.md`. Record outcome, bundle ID, actual verification evidence summary, open risks, next owner, Notion record and Drive repository links, project ID, branch, full base/candidate Git commit IDs, and uncommitted-change disclosure. Git commits and connector code fingerprints are different identifiers. Exclude raw agent transcripts, credentials, private paths, and customer data. Neither a handoff nor an AI review constitutes business acceptance.\n",
        f"{relative}/40 Published/README.md": "# Published Notion context\n\nEnterprise Connector owns CURRENT.md, current.json, and snapshots/. Do not edit them. CURRENT.md is a convenient pointer; validate with shared-status on your device before relying on its advertised snapshot. Drive can deliver files out of order, and offline copies can be stale.\n\nThis is a source-only reading cache. Claude and Cursor use separately validated local task packets with code scope. A green shared snapshot does not validate your local source checkout.\n",
        "20 Playbooks/README.md": "# Playbooks\n\nUse `PB-001--procedure.md`. States: draft → in-review → approved → retired. Required metadata: owner, reviewed_by, reviewed_on, review_due, classification, related_ids, canonical business links. Review every 90 days and when requirements change. Promote required procedure text into explicitly scoped Notion requirements or a reviewed Git technical brief before including it in an agent packet.\n",
        "30 Reference/README.md": "# Reference\n\nStore approved reference links and small, classified attachments under topic folders. Keep large originals in their existing company system and link to them. Reference material is never automatically crawled into model packets.\n",
        "90 Archive/README.md": "# Archive\n\nUse `YYYY/<original-relative-path>`. Archive inactive human notes while retaining stable IDs and canonical links. The publisher separately removes superseded generated snapshots; do not use this folder as a hidden agent memory store. Drive synchronization is not an independent backup.\n",
        "99 System/README.md": "# System metadata\n\nshared-vault.json records one stable logical vault UUID, member labels, project IDs, relative project locations, publisher assignments, and handover epochs. It contains no device paths or credentials. Edit ownership through the reviewed handover workflow; coordinate registry changes with the other member and wait for Drive to synchronize.\n",
        "_templates/note.md": note,
        "_templates/meeting.md": note.replace("type: note", "type: meeting") + "\n## Decisions proposed\n\n## Actions (Notion Work Item links)\n",
        "_templates/proposal.md": note.replace("type: note", "type: proposal").replace("status: working", "status: draft") + "\n## Proposed change\n\n## Alternatives and impact\n\n## Reviewer decision / canonical Notion record\n",
        "_templates/handoff.md": note.replace("type: note", "type: handoff") + "\n## Task and bundle IDs\n\n## Finance repository / branch / base and candidate commits\n\n## Uncommitted changes\n\n## Actual checks and results\n\n## Risks / next owner\n",
        "_templates/playbook.md": note.replace("type: note", "type: playbook").replace("status: working", "status: draft").replace("related_ids: []", "id: PB-001\nreviewed_by: null\nreviewed_on: null\nreview_due: null\nrelated_ids: []") + "\n## When to use\n\n## Steps\n\n## Verification\n\n## Failure handling\n",
    }


def _binding(c, writer=False):
    b = c.get("shared")
    if not isinstance(b, dict) or not isinstance(b.get("vault_path"), str) or not Path(b["vault_path"]).is_absolute():
        raise BridgeError("SHARED_CONFIG", "Initialize a shared-vault binding on this device first.")
    root = Path(b["vault_path"]).resolve()
    for key in ("vault_path", "project_path", "repo_path", "state_dir"):
        local = Path(c[key]).resolve()
        if local.is_relative_to(root) or root.is_relative_to(local):
            raise BridgeError("SHARED_LOCATION", "Local runtime paths must not overlap the shared vault.")
    registry = _registry(root)
    p = registry["projects"].get(c["project_slug"])
    if not p or p["project_id"] != c["project_id"] or b.get("vault_id") != registry["vault_id"] or b.get("project_relative") != p["project_relative"] or b.get("member_id") not in MEMBERS:
        raise BridgeError("SHARED_BINDING", "The shared registry does not match this local project binding.")
    if writer and (b["member_id"] != p["publisher_id"] or b.get("publisher_id") != p["publisher_id"] or b.get("publisher_epoch") != p["publisher_epoch"]):
        raise BridgeError("SHARED_PUBLISHER", "This device is not bound to the current publisher and handover epoch. Stop the old publisher and reinitialize after the handover syncs.")
    return root, registry, p


def _published(root, p):
    return _path(root, p["project_relative"] + "/40 Published")


def _write_invalid(c, root, registry, p, reason_code):
    public = _published(root, p)
    pointer = {"schema_version": 1, "state": "UNAVAILABLE", "vault_id": registry["vault_id"], "project_id": p["project_id"], "publisher_id": p["publisher_id"], "publisher_epoch": p["publisher_epoch"], "checked_at": utc_now(), "reason_code": reason_code}
    atomic_json(_path(public, "current.json"), pointer)
    atomic_text(_path(public, "CURRENT.md"), "# Shared context unavailable\n\nThe publisher has invalidated this reading cache. Wait for a complete, reviewed refresh and validate it with shared-status. Offline devices may still hold older copies.\n")
    return pointer


def _prune_snapshots(c, root, p, current):
    snapshots = _path(_published(root, p), "snapshots")
    previous = []
    for item in snapshots.iterdir():
        if item.name == current:
            continue
        if not PUBLICATION_ID.fullmatch(item.name) or not _path(snapshots, item.name).is_dir():
            raise BridgeError("SHARED_INTEGRITY", "Unexpected content exists inside the generated snapshots folder.")
        metadata = _read_metadata(_path(item, "manifest.json"))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("first_observed_at"), str):
            raise BridgeError("SHARED_INTEGRITY", "An older generated snapshot has invalid metadata.")
        previous.append((metadata["first_observed_at"], item))
    for _, item in sorted(previous, key=lambda entry: entry[0], reverse=True)[2:]:
        destination = core.state_path(c, "quarantine") / ("shared-retired-" + uuid.uuid4().hex)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item), str(contained(Path(c["state_dir"]), destination)))


def invalidate_shared(c, reason_code="STALE"):
    """Persist intent first, invalidate pointer, then quarantine generated bytes."""
    root, registry, p = _binding(c, writer=True)
    if not isinstance(reason_code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", reason_code):
        reason_code = "STALE"
    intent = core.state_path(c, "shared_invalidation.json")
    atomic_json(intent, {"pending": True, "reason_code": reason_code, "at": utc_now()})
    pointer = _write_invalid(c, root, registry, p, reason_code)
    snapshots = _path(_published(root, p), "snapshots")
    if snapshots.exists():
        target = core.state_path(c, "quarantine") / ("shared-" + uuid.uuid4().hex)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(snapshots), str(contained(Path(c["state_dir"]), target)))
        except OSError as exc:
            raise BridgeError("SHARED_QUARANTINE", "Shared invalidation is recorded but generated snapshot removal is pending. Resolve Drive or file access before publishing.") from exc
    atomic_json(intent, {"pending": False, "reason_code": reason_code, "at": utc_now()})
    return pointer


def _publish_shared(c):
    """Publish only reviewed, selected business source text, never local packets."""
    root, registry, p = _binding(c, writer=True)
    pending = core.state_path(c, "shared_invalidation.json")
    if pending.exists() and read_json(pending).get("pending"):
        invalidate_shared(c, "QUARANTINE_PENDING")
    health = core.status(c)
    if health["state"] != "FRESH" or health.get("review_status") != "REVIEW_ACKNOWLEDGED_LOCAL":
        invalidate_shared(c, "REVIEW_REQUIRED" if health["state"] == "FRESH" else "STALE")
        raise BridgeError("SHARED_REVIEW", "Shared publication requires fresh context and an explicit local source-review acknowledgment.")
    manifest = core.check_release(c, health["bundle_id"])
    candidate = read_json(core.state_path(c, "candidate_source.json"))
    if candidate.get("hash") != health["source_hash"] or digest(candidate.get("pages")) != health["source_hash"]:
        invalidate_shared(c, "INTEGRITY")
        raise BridgeError("SHARED_INTEGRITY", "The captured source does not match the verified local release.")
    pages = core.source_material(candidate["pages"], c)
    sections, briefs = core.extract_sections(pages)
    ids = manifest["requirement_ids"]
    body = f"# {p['project_id']} — Published business context\n\nSource mode: {c['mode']}\nSource hash: {health['source_hash']}\nReview: REVIEW_ACKNOWLEDGED_LOCAL\n\nThis reading cache is selected Notion source data. It grants no execution authority or business acceptance. Validate shared-status and the observation time before use.\n\n## Project brief\n" + "\n\n".join(briefs) + "\n\n## Selected requirements\n" + "\n\n".join(sections[i]["text"] for i in ids) + "\n\n## Source references\n" + "\n".join(f"- {page['title']}: {page['url'] or page['id']}" for page in pages) + "\n"
    if core.SECRET.search(body) or LOCAL_PATH.search(body):
        invalidate_shared(c, "SHARED_CONTENT")
        raise BridgeError("SHARED_CONTENT", "Shared business context contains a recognized credential or device path. Remove it from the approved shared source.")
    if len(body.encode("utf-8")) > c["max_packet_bytes"]:
        raise BridgeError("CONTEXT_TOO_LARGE", "Shared source context exceeds the configured packet budget.")
    identity = {"schema_version": 1, "vault_id": registry["vault_id"], "project_id": p["project_id"], "publisher_id": p["publisher_id"], "publisher_epoch": p["publisher_epoch"], "source_hash": health["source_hash"], "source_mode": c["mode"], "review_status": health["review_status"], "requirement_ids": ids, "classifications": sorted({page["classification"] for page in pages}), "context_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    publication_id = digest(identity)[:24]
    shared_manifest = {**identity, "publication_id": publication_id, "first_observed_at": candidate["observed_at"]}
    public = _published(root, p)
    snapshot = _path(public, "snapshots/" + publication_id)
    snapshot.mkdir(parents=True, exist_ok=True)
    _new_text(_path(snapshot, "NOTION_CONTEXT.md"), body)
    _new_text(_path(snapshot, "manifest.json"), json.dumps(shared_manifest, sort_keys=True, indent=2) + "\n")
    existing_manifest = _read_metadata(_path(snapshot, "manifest.json"))
    if not isinstance(existing_manifest, dict) or {k: v for k, v in existing_manifest.items() if k != "first_observed_at"} != {**identity, "publication_id": publication_id} or not isinstance(existing_manifest.get("first_observed_at"), str) or hashlib.sha256(_read_bytes(_path(snapshot, "NOTION_CONTEXT.md"), c["max_packet_bytes"])).hexdigest() != identity["context_sha256"]:
        raise BridgeError("SHARED_INTEGRITY", "An existing immutable shared snapshot differs from its expected content.")
    shared_manifest = existing_manifest
    # Recheck observed ownership before advertising; an offline device can still
    # miss a remote handover. Coordination is required, not just this guard.
    _, latest, latest_project = _binding(c, writer=True)
    if latest != registry or latest_project != p:
        raise BridgeError("SHARED_CHANGED", "Shared registry changed during publication; refresh the binding.")
    pointer = {"schema_version": 1, "state": "FRESH", "vault_id": registry["vault_id"], "project_id": p["project_id"], "publisher_id": p["publisher_id"], "publisher_epoch": p["publisher_epoch"], "publication_id": publication_id, "manifest_hash": digest(shared_manifest), "observed_at": candidate["observed_at"], "checked_at": health["checked_at"], "fresh_until": health["fresh_until"]}
    atomic_json(_path(public, "current.json"), pointer)
    atomic_text(_path(public, "CURRENT.md"), f"# Shared business context\n\nObservation: {candidate['observed_at']}\nFreshness expires: {health['fresh_until']}\nPublisher: {p['publisher_id']} (epoch {p['publisher_epoch']})\n\nValidate shared-status before relying on this pointer. Cloud files may arrive out of order.\n\n- [Selected Notion context](snapshots/{publication_id}/NOTION_CONTEXT.md)\n- [Manifest](snapshots/{publication_id}/manifest.json)\n\nThe local task packet remains authoritative for code scope and verification requirements.\n")
    _prune_snapshots(c, root, p, publication_id)
    return {**pointer, "source_hash": health["source_hash"], "model_calls": 0}


def publish_shared(c):
    # Establish writer eligibility first. A follower never invalidates another
    # member's publication merely because its local profile cannot publish.
    _binding(c, writer=True)
    try:
        return _publish_shared(c)
    except BridgeError as exc:
        if exc.code not in {"SHARED_PUBLISHER", "SHARED_BINDING", "SHARED_CONFIG", "SHARED_CHANGED", "SHARED_QUARANTINE"}:
            invalidate_shared(c, exc.code)
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        invalidate_shared(c, "SHARED_INTEGRITY")
        raise BridgeError("SHARED_INTEGRITY", "Shared publication failed locally; resolve the publication diagnostics before retrying.") from exc


def _shared_status(c):
    """Validate a local replica; FRESH never proves the remote Drive is caught up."""
    root, registry, p = _binding(c)
    public = _published(root, p)
    current = _path(public, "current.json")
    if not current.exists():
        return {"state": "NOT_PUBLISHED", "model_calls": 0}
    pointer = _read_metadata(current)
    if not isinstance(pointer, dict) or pointer.get("schema_version") != 1:
        raise BridgeError("SHARED_INTEGRITY", "Invalid shared publication pointer.")
    for key, expected in {"vault_id": registry["vault_id"], "project_id": p["project_id"], "publisher_id": p["publisher_id"], "publisher_epoch": p["publisher_epoch"]}.items():
        if pointer.get(key) != expected:
            raise BridgeError("SHARED_INTEGRITY", "Shared pointer belongs to a different vault, project, or publisher epoch.")
    if pointer.get("state") != "FRESH":
        return {"state": "UNAVAILABLE", "reason_code": pointer.get("reason_code", "STALE"), "model_calls": 0}
    publication_id = pointer.get("publication_id", "")
    if not isinstance(publication_id, str) or not PUBLICATION_ID.fullmatch(publication_id) or not isinstance(pointer.get("manifest_hash"), str) or not HASH.fullmatch(pointer["manifest_hash"]):
        raise BridgeError("SHARED_INTEGRITY", "Invalid shared publication identity.")
    snapshot = _path(public, "snapshots/" + publication_id)
    manifest = _read_metadata(_path(snapshot, "manifest.json"))
    if not isinstance(manifest, dict) or digest(manifest) != pointer["manifest_hash"] or manifest.get("publication_id") != publication_id or digest({k: v for k, v in manifest.items() if k not in ("publication_id", "first_observed_at")})[:24] != publication_id:
        raise BridgeError("SHARED_INTEGRITY", "Shared snapshot is incomplete or its manifest does not match the pointer.")
    for key in ("vault_id", "project_id", "publisher_id", "publisher_epoch"):
        if manifest.get(key) != pointer[key]:
            raise BridgeError("SHARED_INTEGRITY", "Shared snapshot metadata does not match the current publisher.")
    body = _read_bytes(_path(snapshot, "NOTION_CONTEXT.md"), c["max_packet_bytes"])
    if len(body) > c["max_packet_bytes"] or hashlib.sha256(body).hexdigest() != manifest.get("context_sha256"):
        raise BridgeError("SHARED_INTEGRITY", "Shared context is incomplete, changed, or exceeds the local budget.")
    classes = manifest.get("classifications")
    if manifest.get("review_status") != "REVIEW_ACKNOWLEDGED_LOCAL" or not isinstance(classes, list) or not classes or any(not isinstance(x, str) for x in classes) or not set(classes).issubset(c["allowed_classifications"]):
        raise BridgeError("CLASSIFICATION", "Shared context is unreviewed or outside the reader's allowed classification scope.")
    try:
        now = datetime.now(timezone.utc)
        observed = datetime.fromisoformat(pointer["observed_at"])
        checked = datetime.fromisoformat(pointer["checked_at"])
        expires = datetime.fromisoformat(pointer["fresh_until"])
        age = (now - observed).total_seconds()
        check_age = (now - checked).total_seconds()
        window = (expires - checked).total_seconds()
        fresh = -60 <= age <= c["freshness_seconds"] and -60 <= check_age <= c["freshness_seconds"] and 0 < window <= c["freshness_seconds"] + 1 and expires >= now
    except (KeyError, ValueError, TypeError) as exc:
        raise BridgeError("SHARED_INTEGRITY", "Shared freshness timestamps are invalid.") from exc
    return {"state": "FRESH" if fresh else "STALE", "publication_id": publication_id, "source_hash": manifest["source_hash"], "observed_at": pointer["observed_at"], "publisher_id": p["publisher_id"], "publisher_epoch": p["publisher_epoch"], "replica_note": "Validated local files only; confirm Drive synchronization separately. This is a reading cache, not a local task execution packet.", "model_calls": 0}


def shared_status(c):
    try:
        return _shared_status(c)
    except BridgeError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise BridgeError("SHARED_INTEGRITY", "Shared replica validation failed. Resolve local file synchronization and validate again.") from exc


def transfer_publisher(c, publisher_id, reviewed_hash=None, apply=False):
    """Review and change a local registry replica after a coordinated handover."""
    root, registry, project = _binding(c, writer=True)
    if publisher_id not in MEMBERS or publisher_id == project["publisher_id"]:
        raise BridgeError("SHARED_MEMBER", "Choose the other registered member as the new publisher.")
    plan = {"vault_id": registry["vault_id"], "project_id": project["project_id"], "old_publisher": project["publisher_id"], "new_publisher": publisher_id, "next_epoch": project["publisher_epoch"] + 1, "registry_hash": digest(registry), "coordination": "Stop old refresh schedules; let Drive finish syncing; new publisher reinitializes its local binding after observing this epoch."}
    review_hash = digest(plan)
    if not apply:
        return {**plan, "review_hash": review_hash, "applied": False}
    if reviewed_hash != review_hash:
        raise BridgeError("REVIEW_MISMATCH", "Review the exact current publisher handover plan before applying it.")
    invalidate_shared(c, "PUBLISHER_HANDOVER")
    _, latest, _ = _binding(c, writer=True)
    if latest != registry:
        raise BridgeError("SHARED_CHANGED", "Registry changed during handover; review a new plan.")
    registry["projects"][c["project_slug"]] = {**project, "publisher_id": publisher_id, "publisher_epoch": plan["next_epoch"]}
    atomic_json(_path(root, REGISTRY), registry)
    _write_invalid(c, root, registry, registry["projects"][c["project_slug"]], "PUBLISHER_HANDOVER")
    return {**plan, "review_hash": review_hash, "applied": True}
