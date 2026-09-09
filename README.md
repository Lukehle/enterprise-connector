# Enterprise Connector

Enterprise Connector is a portable, model-free bridge between a work Notion workspace, an Obsidian
vault, and project files used in Cursor. Designed for setup on a **separate
enterprise work machine**. Python 3.11+; no third-party runtime packages.

Read [the exact taxonomy](docs/TAXONOMY.md) for every folder, ID, Notion property,
relation, status option, view, and template. Follow the
[work-machine operating guide](docs/OPERATING_GUIDE.md) for connection and use.

Get the portable ZIP from [GitHub Releases](https://github.com/Lukehle/enterprise-connector/releases/latest).
The command-line utility and local state retain the `work-context` name used by
the setup guides. An installed Python package also provides `enterprise-connector`
as an equivalent command.

## What is built

| Bridge | Implemented behavior |
|---|---|
| Setup → Obsidian/Cursor | Creates one vault, a shared project wrapper, task and note templates, and a small Cursor rule; preserves existing files. |
| Setup → Notion | Plans and explicitly creates Projects, Requirements, Work Items, Decisions, and Automation Updates, including properties and relations. |
| Notion → task context | Captures only configured page IDs, checks completeness and revisions, maps acceptance criteria to rules and dependencies, and compiles versioned packets. |
| Repository → task context | Captures selected code fingerprints, task scope, and the reviewed technical overview without executing project code. |
| Context → Claude/Cursor | Produces CLAUDE_PACKET.md and CURSOR_TASK.md with source references and an immutable manifest. Claude handoff is manual. |
| Local outcome → Notion | Builds a reviewable update draft; explicit publication appends only to this setup's Automation Updates destination with an outbox and duplicate checks. |

No model calls occur in any bridge command. The kit does not install a
background agent or require an LLM API account. Existing Claude/Cursor use and
billing continue through the enterprise's normal accounts.

## The exact top-level organization

```text
WorkVault/
  00 Home/
  01 Inbox/
  10 Projects/<project-slug>/
    repo/                 # implementation, reviewed docs, task contracts
    notes/                # human working notes
    context/              # configuration, packets, status
    .cursor/rules/
  20 Playbooks/
  90 Archive/
  _templates/
```

Notion's **Work Context** parent page contains:

| Collection | Stable IDs | Owns |
|---|---|---|
| Projects | PRJ-001 | Purpose, owner, lifecycle, repository and vault links |
| Requirements | BR-001 / AC-001 / CON-001 | Business rules, acceptance criteria, constraints |
| Work Items | TASK-001 | Business intent, priority, human status, requirement relations |
| Decisions | BD-001 | Business decisions and references to technical ADRs |
| Automation Updates | UPD-… | Explicitly published outcome summaries |

Technical decisions remain `ADR-001` files in Git. Notion business status and
the local technical task contract have different owners. There is no automatic
two-way edit of requirements or task-board status.

## Quick start on the work machine

Transfer and extract the complete kit through the approved work process.
From its folder, with an approved Python runtime:

```powershell
python .\work-context.py init --vault 'C:\Work\WorkVault' --project forecast-automation
```

The example path is a choice for the work machine, not a preconfigured location.
Initialization prints `config_path`. It starts **unconfigured**, without
contacting Notion. Source selection, local credential setup, reviewed schema
creation, and publication are in the operating guide.

To try a fully local synthetic example instead:

```powershell
python .\work-context.py init --vault 'C:\Work\WorkVault-Demo' --project forecast-automation --demo
$wcDemoConfig = 'C:\Work\WorkVault-Demo\10 Projects\forecast-automation\context\config.json'
python .\work-context.py --config $wcDemoConfig sync
python .\work-context.py --config $wcDemoConfig packet --for cursor
```

Open the vault root in Obsidian. Open only
`10 Projects\forecast-automation` in Cursor. Both applications see the same
files; no Obsidian plugin or sync subscription is required for that local setup.

Optional [PowerShell wrappers](scripts/README.md) perform the same commands.
They do not download software or change PowerShell policy.

## Verification and operating limits

Run the included tests without Notion credentials:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

Tests cover source completeness, state isolation, approval metadata, policy
changes, rule dependencies, stale packets, deterministic releases, credential
handling, uncertain writes, and duplicate publication. HTTP tests use simulated
responses. A work-account smoke test is still required after connection.

- Notion bootstrap creates the database schemas and default tables. Named
  views, UI page templates, initial business records, and update relations are
  specified exactly but completed manually in Notion.
- Requirement rows need consistent Type, External ID, Status and Classification.
  Only human-marked Approved rows can receive a local source-review acknowledgment.
- A local acknowledgment is **not protected enterprise authorization**.
  This kit does not implement an execution sandbox, trusted test runner,
  autonomous repair controller, or business acceptance service.
- Packet freshness expires after 15 minutes by default. Source changes are
  discovered on the next explicit sync. `status` evaluates capture age,
  configuration and local files; it does not contact Notion.
- Access loss quarantines previous releases in local state and blocks the
  current pointer. It cannot retract content already pasted into another app.
- A few credential patterns are rejected as a guardrail. This is not a general
  secret detector or data-loss-prevention system.
- Obsidian notes and playbooks are excluded from automatic packets. Add required
  technical procedure text to the reviewed brief or an explicit business source.
- Runtime state, source cache and write journals remain outside the vault, bound
  to that specific project. Do not share a state directory across vaults.
- Secrets are supplied locally through `NOTION_READ_TOKEN` and, only for chosen
  writes, `NOTION_WRITE_TOKEN`. They are not stored by the kit.

The dedicated Notion writer needs read access to its own destination for
duplicate reconciliation. Keep its source-writing permissions restricted.
An ambiguous create stops for reconciliation; deleting its journal and retrying
can create duplicates.

This is the bridge implementation, not the full autonomous-harness proposal.
Measure actual extra usage and accepted-task throughput before adding automation.
