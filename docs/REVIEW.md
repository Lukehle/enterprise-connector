# Release review: v0.2.0

Reviewed 2026-09-09. This release is a portable context connector for a work Mac.
It implements the deterministic bridges and setup tooling from the broader
harness proposal. It does not implement autonomous execution or establish
enterprise approval. The first live work-account smoke test remains local to
the target environment.

## Review scope and changes

Independent code, security and delivery passes examined source capture,
repository fingerprinting, packet integrity, review receipts, filesystem
failures, Notion permissions/writes, installation and release packaging.
Concrete failures were reproduced before fixes and covered by regression tests.

| Finding | Resolution / verification |
|---|---|
| Code under nested docs/tasks/context folders, or outside default globs, could be missed | Fingerprint includes those folders and unions the task's allowed_files with configured patterns. Tests edit both cases and require STALE. |
| Unreadable directories or special files could undermine capture | Walk errors fail capture; included files must be bounded regular files and stable across reads. POSIX FIFO test verifies rejection without opening. |
| Failed quarantine could retain FRESH or lose the pending operation after a crash | Persist invalid health and quarantine intent before rendering/moving; revoke review; retry pending quarantine before another capture. Tests cover permission failures and interruption. |
| Source restrictions left old packets visible | Configuration changes, access loss and disallowed classification quarantine visible releases and revoke source review. |
| Live connection-check access failure did not invalidate old source context | Source check failures update health and quarantine. Separate schema-only diagnostics do not falsely revoke readable sources. |
| Workspace edits to both packets and manifest escaped file-hash checks | Entire manifests are bound to independent local-state receipts. Tests rewrite packet bodies, hashes and claimed evidence and require failure. |
| Validation errors left the persisted status/pointer fresh | Status validation records failed/stale state and invalidates the visible pointer. |
| Damaged deterministic release could not be regenerated | Explicit sync --repair quarantines the damaged release and compiles from a new capture. |
| Mac linked-parent and tilde paths disagreed with state identity | Canonical resolved identities and expanduser handling; dedicated macOS Application Support default. |
| Notion metadata could change inside a capture with the same timestamp | Compare the properties used by compilation as well as revision metadata. |
| Bootstrap resume trusted existing schemas too much | Verify live property types, select options and relation destinations before continuing. |
| Uncertain Notion creates lacked a usable recovery path | Explicit database/page reconciliation validates an identified candidate and updates the local journal without repeating POST. |
| Update classification and associations were manual | Draft classification and optional project/work-item relations are hash-bound and destination-validated. |

The kit now also creates twelve named Notion views, exports five Markdown
templates, performs read-only connection diagnostics, and includes Mac Bash
wrappers, Windows wrappers, an offline self-test and a standalone archive verifier.

## Reproducible release gates

Run the full test suite, offline self-test, source-only package builder and
extracted-archive smoke test before publishing. GitHub Actions performs these
checks on macOS, Ubuntu and Windows with Python 3.11 and 3.14. POSIX-specific
FIFO/symlink and Mac Bash wrapper tests run on macOS/Linux; Windows wrapper tests
run on Windows. A platform skip on one OS is exercised by the other matrix jobs.

[Workflow](../.github/workflows/ci.yml) •
[Run history](https://github.com/Lukehle/enterprise-connector/actions/workflows/ci.yml)

The package uses an explicit reviewed file allowlist, synchronized version
numbers, normalized text, per-file SHA-256 manifest and archive checksum. Its
smoke test extracts into a temporary directory, verifies the manifest, executes
the offline workflow, and requires a nonempty passing test suite. Public release
inputs contain synthetic examples and generic setup guidance; the original
private handoff document, vaults, runtime state and credentials are excluded.

## Remaining work-machine validation

- Supply the approved Python runtime, Obsidian/Cursor setup, Notion integrations
  and actual page IDs on the Mac. Run self-test and connection-check there.
- Apply the reviewed schema/views in the intended workspace. Create native
  Notion template UI objects from the exported Markdown; add real business rows.
- Perform one small live capture and optional reviewed publication. HTTP tests
  simulate API behavior; CI has no enterprise tokens or tenant access.
- Confirm company data-flow rules and the installed editor's project-rule behavior
  through the normal work setup process. This package does not inspect device
  management, SSO, company policies or Claude/Cursor account entitlements.

## Explicit trust and operating boundaries

Source text is data, never authority to change permissions. Local acknowledgments,
receipts, .cursorignore and task file patterns are same-user guardrails, not a
sandbox or protected enterprise authorization. The source cache and journals
contain work data and need work-approved storage and backup.

Freshness is relative to the last capture. Remote revocation or edits are known
only after a live read. Quarantine cannot erase content already pasted or cached
by another application. Old successful releases remain historical artifacts;
use only the current pointer after a status check.

No model calls, project-code execution, autonomous repair controller, trusted
verification runner, deployment or business acceptance is provided. The Notion
publisher records reviewed human observations with explicit bridge limitations.
Remote payload hashes support duplicate reconciliation; they are not proof
against subsequent human editing of the Notion page. Native template creation
and initial business ownership remain manual.

The original design was assessed as B+ with a plausible context-reuse benefit.
The savings case is still unproven: track paid overage, accepted-task throughput
and preparation/review time before expanding the harness.
