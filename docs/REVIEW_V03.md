# v0.3 review: shared work context and model routing

This candidate extends v0.2 for a shared Obsidian vault in company Google Drive,
with Luke and Boss as collaborators. It is prepared for repository review before
a new stable release. It does not connect this personal machine to a work tenant.

Finance projects use Git stored in company Google Drive. GitHub hosts the public
connector kit and its own review/CI only. Finance review uses local diffs, commit
IDs and Notion records. [FINANCE_GIT.md](FINANCE_GIT.md) distinguishes the existing
Drive repository from each Mac's active checkout and the shared notes vault;
the connector does not perform Git transfers or claim Drive is a Git server.

## Design decisions

| Concern | Implemented decision |
|---|---|
| Google Drive replicas disagree on local paths | Shared registry contains logical IDs and relative paths; each Mac creates a separate local execution workspace and private state. |
| Both people edit/generated files conflict | Member-owned note folders; one designated publisher with a handover epoch; human synchronization procedure. No distributed-lock claim. |
| Duplicate sources become inconsistent | Notion owns approved business meaning/status; Obsidian owns notes; Git owns implementation/ADRs. Notes are promoted through human review and linked back. |
| Repeated context discovery costs model turns | Read explicit Notion pages without models; compile selected rules and dependencies into bounded local packets and stage handoffs. |
| Automatic updates silently approve changes | Five-minute refresh is deterministic; a changed source hash waits for review before shared publication. |
| Interrupted/partial cloud transfer | Immutable content manifests, advertised pointer, expiry and reader-side integrity validation; no promise of atomic Drive propagation. |
| Known source loss leaves stale shared authority | Invalidate shared current state and quarantine generated snapshots locally; retain durable retry intent on file failures. |
| Background credential handling | Optional existing Keychain item read into memory; schedule carries only service/account references. No token in plist or shared files. |
| Model aliases change meaning | Reference Opus4.8/Haiku/Sonnet5 IDs, explicit locally verified model profiles, observed-model recording; Cursor Composer explicitly selected. |
| Failed builds loop indefinitely | Two failed candidates then one Sonnet recovery for Claude; bounded stop for Cursor. Review rejection consumes budget. |
| Infrastructure/quota block hides previous attempts | Explicit prerequisite-restoration evidence resumes only blocked runs while preserving plan and counters. |
| Model success is mistaken for verification | Human-inspected test/review evidence is hash-bound to run, step and candidate; no assertion that a model process exit means tests passed. |

## What the code does

`init-shared` scaffolds collaboration folders and binds a private local profile.
`shared-publish`, `shared-status` and `shared-handover` operate on generated reading
context and observed publisher ownership. `refresh` captures sources and updates
eligible shared context. `refresh-schedule` exports a reviewed macOS LaunchAgent;
installation/start are explicit work-Mac steps.

`route-template`, `route-init`, `route-next`, `route-record` and `route-resume`
prepare exact model commands, maintain a bounded stage ledger and copy evidence
into private state. They do not launch models or run tests. Claude plans/reviews
with Opus 4.8, builds with Haiku and receives one Sonnet 5 recovery after two failed
candidates. Cursor plans/reviews with Opus 4.8 and builds with Composer.

## Verification required before review-ready publication

- Run all existing source-capture, Notion, packaging and Mac/Windows wrapper tests.
- Run shared-vault tests for two profiles, immutable snapshots, classification,
  partial transfer, access loss, publisher handover and retention.
- Run routing tests for both workflows, failure counting, evidence integrity,
  context/candidate changes, model pins, blocked resume and budget exhaustion.
- Run refresh/CLI integration tests for review-gated publication, invalidation,
  Keychain failure, absence of credential persistence and reviewed schedule export.
- Build the explicit-file ZIP and run its extracted self-test and full suite.
- Run the CI matrix: macOS, Ubuntu and Windows × Python 3.11 and 3.14.

Exact results and CI links are recorded in the pull request. The review excludes
live company credentials, paid model calls, actual dual-Mac Drive propagation and
installing a LaunchAgent on the user's work Mac. These are target-environment
checks, not simulated claims.

## Residual limits and rollout

Drive is asynchronous file synchronization, not collaborative document locking.
Offline clients can retain old bytes or miss a publisher handover. Both members
must follow the stop/sync/rebind procedure, compare conflict copies and use work
backups. Per-device Obsidian configuration folders still synchronize and cannot
hold private secrets.

Shared snapshots are reading caches. Local execution packets remain the task
contract handed to Claude/Cursor; neither is protected enterprise authorization.
Receipts and evidence ledgers are editable by the same OS user. Fingerprinting
and allowed-file checks observe configured scope; they do not sandbox the agent.

The routing controller selects the next stage from recorded outcomes. Running
the client, verifying actual model identity, running meaningful tests, inspecting
evidence and accepting business behavior remain explicit. Company-managed MCPs,
plugins, hooks and policy can remain active; inspect the effective client context.
Savings require measurement of accepted-task cost, retries, human review and
usage-limit frequency. Vendor subscription allowances are not increased by this kit.

Begin with one synthetic project and one designated publisher. Verify local
self-test, source sharing, one reviewed snapshot on both Macs, one code task's
route, a failed-candidate escalation, a stopped refresh and a coordinated handover
before expanding the shared vault.
