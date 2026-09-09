# Enterprise Connector

Local, model-free context bridges for Notion, Obsidian, Claude Code and Cursor.
The v0.3 review candidate adds a **shared Google Drive vault for Luke and Boss**,
separate per-Mac execution workspaces, scheduled context refresh and bounded
model routing. Python 3.11+; no third-party runtime packages.

This branch is prepared for review. The [published stable download](https://github.com/Lukehle/enterprise-connector/releases/latest)
remains v0.2 until the new shared workflow is reviewed and released.

## Read in this order

1. [Shared vault: exact folders, ownership, Notion connections and two-Mac setup](docs/SHARED_VAULT.md)
2. [Self-updating context: five-minute refresh and Mac schedule](docs/SELF_UPDATE.md)
3. [Model routing: Opus / Haiku / Sonnet and Cursor Composer](docs/MODEL_ROUTING.md)
4. [Notion properties, IDs, views and templates](docs/TAXONOMY.md)
5. [Review scope and remaining work-machine checks](docs/REVIEW_V03.md)

[Notion API setup](docs/NOTION_SETUP.md) •
[Single-user setup](docs/OPERATING_GUIDE.md) •
[Work-machine checklist](docs/WORK_MACHINE_CHECKLIST.md)

## Three separate locations

| Location | Contents | Writers |
|---|---|---|
| Company Google Drive shared Obsidian vault | Working notes, meetings, proposals, playbooks, links, and selected published Notion reading context | Luke and Boss in their owned note folders; one designated publisher for generated files |
| Each Mac's local execution workspace | Git repository, technical overview, task contracts, Cursor rule and bounded Claude/Cursor packets | That Mac's reviewed development workflow |
| Each Mac's private Application Support state | Source cache, local config references, review receipts, routing/evidence ledger, outbox and quarantine | Local connector commands |

Do not move the existing v0.2 execution vault wholesale into Google Drive.
`init-shared` creates the shared collaboration structure while keeping machine
paths and executable project state local. Google Drive synchronization is not a
distributed lock; designate one publishing Mac and coordinate handovers.

## Shared folder taxonomy

```text
WorkVault/                         # shared in company Google Drive
  00 Home/                        # navigation, agreement, people, ID register
  01 Inbox/luke/ and boss/         # separate capture ownership
  02 Meetings/                    # dated meeting records
  10 Projects/<project-slug>/
    00 Overview/
    10 Notes/luke/ and boss/
    20 Proposals/
    30 Handoffs/
    40 Published/                 # generated, reviewed Notion reading snapshots
  20 Playbooks/
  30 Reference/
  90 Archive/
  _templates/
  99 System/                      # logical shared IDs and publisher epoch only
```

Notion owns Projects, Requirements, Work Items, Decisions and Automation Updates.
Git owns code, tests and technical ADRs. Obsidian owns collaboration notes.
Promote a note through human review into its canonical Notion record, then keep a
link in the vault. Avoid separately editable copies of the same approved rule.

## Start on the work Mac

Run from this branch's complete kit folder with your approved Python runtime:

```bash
python3 work-context.py self-test
shared_vault='<absolute Google Drive vault path copied from Finder>'
python3 work-context.py init-shared --shared-vault "$shared_vault" --local-workspace "$HOME/Work/ExecutionWorkspace" --project forecast-automation --member-id luke --publisher-id luke
```

Boss runs the same initialization on their own Mac with `--member-id boss` after
the shared registry has synchronized. Each person opens the shared root in
Obsidian. Cursor opens the LOCAL execution project's wrapper. Follow the shared
vault guide for Drive offline availability, per-device Obsidian configuration,
sharing, conflict handling and publisher handover.

The designated publisher uses `refresh` for a complete Notion capture and reviewed
shared projection. Changed business content waits for source review. A reviewed
`refresh-schedule` exports a five-minute LaunchAgent for installation on the work
Mac; it never schedules model calls or publishes business updates automatically.

## Model routing

| Workflow | Planning and review | Building | Recovery |
|---|---|---|---|
| Claude Code CLI | Opus 4.8 | Haiku | Sonnet 5 after two failed candidates, one recovery attempt |
| Cursor | Opus 4.8 | Cursor Composer | Stop for human diagnosis after two failed candidates |

`route-template`, `route-init`, `route-next` and `route-record` prepare commands,
small handoffs and a private evidence ledger. The next stage is selected from
recorded outcomes. These commands do not execute models or tests. Exact model
availability must be checked on the work account; moving model aliases are
refused. Opus review and human business acceptance remain separate.

The cost reduction comes from reusing a small local packet and short stage
handoffs instead of repeated remote discovery and growing transcripts. Claude
commands use a minimal optional MCP/tool profile; Cursor's effective MCP list is
checked locally. Company-managed tools and policies remain authoritative. This
does not expand usage limits or guarantee savings; measure paid overage and total
cost per accepted task, including failed attempts and human review.

## What is built and tested

- Five Notion schemas, relations, twelve named views and five Markdown templates.
- Explicit source scope, complete/revision-consistent capture and dependency mapping.
- Source-review receipts, bounded packets, fingerprints, stale-state checks and repair.
- Shared-vault scaffold, publisher epochs, snapshot integrity, expiry and invalidation.
- Mac refresh schedule export with optional in-memory Keychain credential lookup.
- Bounded model routing, evidence binding and reviewed update publication.
- Deterministic source-only ZIP, manifest verifier and offline self-test.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/package_kit.py
python3 scripts/verify_kit.py dist/enterprise-connector-v0.3.0.zip --smoke
```

CI runs on macOS, Windows and Ubuntu with Python 3.11 and 3.14. Tests use synthetic
content and simulated HTTP responses. Actual enterprise Notion access, two-device
Drive propagation, installed Claude/Cursor behavior and LaunchAgent/Keychain
permissions must be checked on the work machines. No work credentials or live
company content belong in this public repository.
