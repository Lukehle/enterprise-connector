# Work Mac setup and daily operation

For Luke and Boss's shared Google Drive vault, start with
[SHARED_VAULT.md](SHARED_VAULT.md), then [SELF_UPDATE.md](SELF_UPDATE.md) and
[MODEL_ROUTING.md](MODEL_ROUTING.md). This guide retains the single-user layout
and common Notion operations. Shared setup keeps the execution workspace local.

Enterprise Connector runs locally with Python 3.11 or newer and no third-party
runtime packages. Obsidian and Cursor share the same files. Notion is the source
of selected business context. Claude receives a deliberate Markdown handoff.

The work projects use Git in company Google Drive. GitHub is only where the
generic connector kit is distributed; finance projects need no GitHub service.
Follow [FINANCE_GIT.md](FINANCE_GIT.md) when attaching their local checkout.

Use the [exact taxonomy](TAXONOMY.md), [Notion setup guide](NOTION_SETUP.md), and
[work-machine checklist](WORK_MACHINE_CHECKLIST.md) alongside these steps.
Windows alternatives are in [scripts/README.md](../scripts/README.md).

## 1. Verify the download on the Mac

Download the ZIP and matching `.sha256` file from the GitHub release to the same
folder. In Terminal there, check the archive before extracting:

```bash
shasum -a 256 -c enterprise-connector-v0.2.0.zip.sha256
unzip enterprise-connector-v0.2.0.zip
cd enterprise-connector
python3 work-context.py self-test
```

Use an empty extraction destination for each version. If `python3` is absent or
older than 3.11, select an existing work-approved runtime; the kit does not
install one. Self-test uses a temporary synthetic vault, removes it afterwards,
and makes no network or model calls. A release ZIP also checks its file manifest.
The checksum verifies the downloaded bytes against the accompanying file; it
is not an independently signed publisher identity.

Keep code and work data in work-approved locations. Initialize configuration and
credentials on the work machine; a configuration copied from another computer
contains that computer's absolute paths and state binding.

## 2. Inspect an isolated demonstration

```bash
bash scripts/Install-WorkContext.sh --vault "$HOME/Work/WorkVault-Demo" --project forecast-automation --demo
wc_demo_config="$HOME/Work/WorkVault-Demo/10 Projects/forecast-automation/context/config.json"
python3 work-context.py --config "$wc_demo_config" sync --task TASK-001
python3 work-context.py --config "$wc_demo_config" status
python3 work-context.py --config "$wc_demo_config" packet --for cursor
```

Open `~/Work/WorkVault-Demo` as an existing vault in Obsidian. Open its
`10 Projects/forecast-automation` folder in Cursor. Read `context/START_HERE.md`
and the linked packets. This is one physical copy shared by both applications.

`FRESH` means the capture and candidate match the local freshness policy.
`REVIEW_REQUIRED` means that exact source capture has no local acknowledgment.
Inspect the synthetic source and packet, then use the returned `source_hash`:

```bash
python3 work-context.py --config "$wc_demo_config" approve-source --reviewed-hash '<source_hash>' --actor '<reviewer-name>'
python3 work-context.py --config "$wc_demo_config" sync
```

The next packet reports `REVIEW_ACKNOWLEDGED_LOCAL`. This records a human review
of the local source capture. It does not grant execution permission or establish
that implementation, tests or business acceptance are complete.

## 3. Initialize the real vault

```bash
bash scripts/Install-WorkContext.sh --vault "$HOME/Work/WorkVault" --project forecast-automation --self-test
wc_config="$HOME/Work/WorkVault/10 Projects/forecast-automation/context/config.json"
python3 work-context.py --config "$wc_config" doctor
```

These paths are examples. Choose the work-approved location, keeping runtime
state outside the vault and outside personal cloud sync. On macOS the default
state directory is `~/Library/Application Support/WorkContext/<slug>-<vault-hash>`.
The hash distinguishes vaults with the same project slug. Explicit `--state-dir`
paths must also be separate and are bound to their owning project.

Use `--project-id PRJ-002` and a new slug for another project. Initialization
preserves existing content and configuration. It starts `unconfigured` and
makes no live Notion request. It creates a starter technical overview and task
contract; replace their synthetic assumptions before using real requirements.

Put the real project implementation in the wrapper's `repo` folder through your
normal Git workflow. The bridge does not clone or initialize a repository. Keep
human working notes in the sibling `notes` folder. Fill `repo/docs/AI_OVERVIEW.md`
and `repo/tasks/TASK-001/task.json` deliberately.

For an existing project, clone into that local `repo` location **before** running
the initializer, which preserves existing files and creates missing scaffolding.
An already initialized `repo` contains starter files and is not an empty clone
destination. Preserve that wrapper and use a new empty local workspace, or have
the repository owner reconcile the starter files deliberately. Never delete or
overwrite work just to make `git clone` accept its destination.

The configuration initially allows Public and Internal classifications, expires
freshness after 900 seconds, and limits each packet to 24,000 UTF-8 bytes and
6,000 estimated tokens. The estimate is bytes divided by four, not vendor usage.
Review these limits for the actual project. `repo_include` plus the task's
`allowed_files` determine fingerprint scope; these are change detectors, not
operating-system write restrictions.

## 4. Create and connect Notion

Create/select the **Work Context** parent page in the enterprise workspace.
Provision the connections using your work-approved credential mechanism:
`NOTION_READ_TOKEN` for source reads; `NOTION_WRITE_TOKEN` only for intentional
setup/publication. Tokens are read from the process environment and are never
stored by the kit. The writer needs read access to its destination for schema
validation and duplicate reconciliation.

Plan the exact five-collection schema:

```bash
python3 work-context.py --config "$wc_config" notion-bootstrap --parent-page '<Work-Context-page-URL-or-ID>'
```

Inspect the returned destination, schemas and `reviewed_operation_hash`, then
apply the same reviewed plan:

```bash
python3 work-context.py --config "$wc_config" notion-bootstrap --parent-page '<Work-Context-page-URL-or-ID>' --apply --reviewed-hash '<operation-hash>'
python3 work-context.py --config "$wc_config" notion-views
python3 work-context.py --config "$wc_config" notion-views --apply --reviewed-hash '<view-plan-hash>'
python3 work-context.py export-notion-templates --output "$HOME/Work/NotionTemplates"
```

The first apply creates schemas and relations. The view command creates the 12
named views from the taxonomy. Exported Markdown supplies the five native
Notion database templates; installing those template UI objects remains a
manual step. Follow [Notion setup](NOTION_SETUP.md) for exact instructions,
required connection sharing and recovery commands.

Create the initial Project row, BR/AC/CON requirement rows, and Work Item with
IDs matching the local contract. Owners, approved statuses and real business
content come from your work process. The bridge does not invent work records.

Explicitly allowlist the project brief and every required rule/criterion page:

```bash
python3 work-context.py --config "$wc_config" configure-notion --page-id '<project-brief-page-ID>' --page-id '<BR-001-page-ID>' --page-id '<AC-001-page-ID>' --reviewed-scope
python3 work-context.py --config "$wc_config" connection-check
python3 work-context.py --config "$wc_config" sync --task TASK-001
```

`connection-check` verifies read access without saving source content. Add
`--include-bootstrap` to validate registered schemas too; this requires sharing
those collections with the read connection. It does not test insert capability.

`--reviewed-scope` acknowledges the chosen source boundary. It does not review
the source contents. Inspect the capture and packet, acknowledge the returned
source hash, then sync again as in the demo. Requirement rows must have a
consistent Type, External ID, explicit Classification and human-maintained
Approved status before local acknowledgment.

Referenced pages and relation targets are not captured automatically. The
contract's `criteria_rules` maps each acceptance ID to its required rules;
`rule_dependencies` adds other required IDs. Structured `Depends On IDs` from
captured rows also participates. All required pages must be allowlisted. The
compiler cannot discover a forgotten dependency from prose.

## 5. Start and finish a task

```bash
python3 work-context.py --config "$wc_config" sync --task TASK-001
python3 work-context.py --config "$wc_config" status
python3 work-context.py --config "$wc_config" packet --for cursor
```

Review freshness and source acknowledgment separately. Cursor reads the
returned packet plus relevant current source files. Confirm its small project
rule is loaded. `.cursorignore` reduces accidental indexing of notes and
fixtures; it is not an access-control boundary. Follow the current pointer,
not an older release link from a previous conversation.

For a Claude design/review pass:

```bash
python3 work-context.py --config "$wc_config" packet --for claude
```

Paste/upload the returned `CLAUDE_PACKET.md` to the approved Claude workspace.
The kit does not synchronize Claude conversations or use a Claude API account.
Record the task and bundle IDs with the resulting review.

Run the actual project's reviewed tests through its established workflow.
Record the command, result and evidence with the implementation. This connector
never executes project code or decides business acceptance. The Work Item
owner updates verification and acceptance from real evidence. Code edits make
the old candidate stale; sync generates a new packet while unchanged business
source review remains valid.

No scheduler is installed. Refresh explicitly at task start and before preparing
an update. `status` checks capture age and local changes; only `sync` discovers
remote Notion edits. File-based pointers cannot retract material already opened
or pasted into another application.

## 6. Publish an outcome

After a fresh sync, draft your actual observations locally:

```bash
python3 work-context.py --config "$wc_config" draft-update --title 'TASK-001 mapping validation update' --summary '<actual outcome, check evidence, limitations and next action>' --classification Internal --project-page-id '<Project-row-page-ID>' --work-item-page-id '<Work-Item-row-page-ID>'
```

Relations are optional; when supplied, they are checked against the destination
relation schema. Classification and relation IDs are bound to the draft hash.
Generated bridge observations truthfully retain NOT_RUN / NOT_RECORDED for
verification, business acceptance and deployment. A human-supplied summary is
not automatically verified evidence.

Review the draft and the registered Automation Updates **data-source ID**:

```bash
python3 work-context.py --config "$wc_config" publish --draft '<draft_path>' --data-source-id '<updates-data-source-ID>'
python3 work-context.py --config "$wc_config" publish --draft '<draft_path>' --data-source-id '<updates-data-source-ID>' --apply --reviewed-hash '<operation-hash>'
```

Apply refreshes the source before sending and refuses a stale draft. Publication
appends to Automation Updates; it does not change requirements or business
statuses. Correct an update with a new reviewed draft. Preserve the outbox journal.

## Recovery and upgrades

| Diagnostic | Next action |
|---|---|
| NOT_CONFIGURED / AUTH_REQUIRED | Set explicit source scope and provision the local read credential. |
| STALE | Sync; inspect code, task, overview, configuration or age changes. |
| MISSING_REQUIREMENT / DUPLICATE_ID | Fix explicit scope, stable IDs and the reviewed dependency mapping. |
| INCOMPLETE | Resolve unsupported/truncated content, revision changes or sharing. |
| CONTEXT_TOO_LARGE | Split the task or shorten an approved brief; required rules are never dropped. |
| INTEGRITY | Inspect the modified packet, then run `sync --task TASK-001 --repair`. It quarantines the damaged release and recaptures current sources. |
| QUARANTINE_PENDING | Resolve filesystem permissions/open-file problems. Sync retries quarantine and blocks new packets until it completes. |
| BOOTSTRAP_UNCERTAIN / WRITE_UNCERTAIN | Inspect Notion; use the explicit candidate-ID reconciliation in the Notion guide. Do not discard journals to force a retry. |
| BUSY | Let the other command release the project lock, then retry. |

For an upgrade, extract a fresh kit folder, verify it, and run self-test. Point
the new launcher at the existing work-machine config. An updated compiler makes
old packets stale; sync compiles a new release. The v0.1 schema registry can be
reused only after its live schema is validated. Back up vault notes and private
state using the work backup process. State contains source captures and drafts;
it needs the same care as the original work data.

For the pilot, record extra paid usage, accepted tasks before hitting a limit,
and human preparation/review time, including failed attempts. This determines
whether the smaller context packets repay the additional process overhead.
