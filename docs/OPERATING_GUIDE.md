# Work-machine setup and daily operating guide

This is a portable setup kit for the separate enterprise work machine. The
included demonstration uses synthetic requirements. The bridge performs no
model calls and installs no Obsidian plugin, scheduler, autonomous worker, or
test runner.

Use [`TAXONOMY.md`](TAXONOMY.md) for the exact folder and Notion property names.
The first pilot is `PRJ-001` / `forecast-automation` / `TASK-001`.

## 1. Copy and verify the kit on the work machine

Copy the kit's source, scripts, tests, and documentation through the approved
transfer process into a tools folder such as `C:\Work\Tools\enterprise-connector`.
Do not copy a personal vault, credential, live state registry, or captured work
data between machines. Use the enterprise's approved Python 3.11 or newer.
The command-line launcher runs directly; installation and third-party Python
packages are not required.

Open PowerShell in the kit folder. Check the available commands:

```powershell
python .\work-context.py --help
```

The commands below assume that working directory. If the enterprise uses a
specific Python executable, substitute that executable for `python`.

## 2. Run an isolated synthetic demonstration

Choose separate demonstration paths; do not reuse the live project state.

```powershell
python .\work-context.py init --vault 'C:\Work\WorkVault-Demo' --project forecast-automation --state-dir "$env:LOCALAPPDATA\WorkContext\demo-forecast-automation" --demo
$wcDemoConfig = 'C:\Work\WorkVault-Demo\10 Projects\forecast-automation\context\config.json'
python .\work-context.py --config $wcDemoConfig sync --task TASK-001
python .\work-context.py --config $wcDemoConfig status
python .\work-context.py --config $wcDemoConfig packet --for cursor
```

The sync result returns the source hash, bundle ID, packet path, zero model
calls, and review status. `FRESH` means the capture and local candidate are
current according to the local freshness policy; it does not mean the source
has been reviewed. Initially, `review_status` is `REVIEW_REQUIRED`. The generated
packet can be inspected while that review is pending.

Open `C:\Work\WorkVault-Demo` as an existing vault in Obsidian. Open
`C:\Work\WorkVault-Demo\10 Projects\forecast-automation` as the Cursor folder.
Read `context\START_HERE.md` and its release links in both applications. There
is one copy of each file on disk.

To exercise source review, inspect the synthetic source and generated packet,
then use the exact `source_hash` returned by sync:

```powershell
python .\work-context.py --config $wcDemoConfig approve-source --reviewed-hash '<source_hash-from-sync>' --actor '<reviewer-name>'
python .\work-context.py --config $wcDemoConfig sync --task TASK-001
```

The next release reports `REVIEW_ACKNOWLEDGED_LOCAL`. The command records your
review of that exact local capture. It is not protected enterprise
authorization, a substitute for the business review process, permission to run
project code, or evidence that a task passed tests.

## 3. Initialize the real work vault

Use the approved work-machine locations. These examples keep the vault and
runtime state separate and outside a general cloud-sync folder:

```powershell
python .\work-context.py init --vault 'C:\Work\WorkVault' --project forecast-automation --state-dir "$env:LOCALAPPDATA\WorkContext\forecast-automation"
$wcConfig = 'C:\Work\WorkVault\10 Projects\forecast-automation\context\config.json'
python .\work-context.py --config $wcConfig doctor
```

Use `--project-id PRJ-002` and a new slug for the next project. When `--state-dir`
is omitted, the default state folder includes the slug and a vault-path hash so
separate vaults do not accidentally share state. Explicit state directories
are also bound to their owning project.

This creates a scaffold with `mode: unconfigured`. There is no live Notion read
until the source allowlist is configured. Fill the technical overview and task
contract deliberately; the starter text is not a real company's requirements.

The tool uses `repo` as the project repository folder and does not initialize
or clone Git automatically. Put the actual project implementation there using
the approved Git workflow. Keep human notes in the sibling `notes` directory.
Scaffold reruns preserve existing content and config; they do not reset a live
setup into demo mode or replace an edited project contract.

Default config values allow `Public` and `Internal` source classifications,
expire freshness after 900 seconds, and limit each packet to 24,000 UTF-8 bytes
and 6,000 estimated tokens. Review configuration against the actual project.
Token estimates use bytes divided by four and are not vendor billing counts.
The kit does not infer authorization from these defaults.

## 4. Create the Notion taxonomy

Create or select the intended Notion parent page named **Work Context** in the
enterprise workspace. The setup command creates five empty databases beneath
that page; it does not migrate existing databases or generate fake business
records. If you already have these collections, inspect them against the schema
and configure their existing source pages instead of creating duplicates.

Use a Notion connection with the enterprise-approved access. Provision
`NOTION_READ_TOKEN` for the read-only source connection through the work
machine's approved credential mechanism. Provision `NOTION_WRITE_TOKEN` only
for the bootstrap or publication operation with access to the intended
destination. The tokens are read from the current process environment and are
not stored in config, the vault, or the kit. Do not place a credential in these
command examples or a task packet.

Prepare the exact creation plan without writing to Notion:

```powershell
python .\work-context.py --config $wcConfig notion-plan --parent-page '<Work-Context-page-URL-or-ID>'
python .\work-context.py --config $wcConfig notion-bootstrap --parent-page '<Work-Context-page-URL-or-ID>'
```

Inspect the destination and all five schemas in the returned plan. The second
command is also a dry run unless `--apply` is supplied. To apply the exact
reviewed plan, use the `reviewed_operation_hash` returned by that command:

```powershell
python .\work-context.py --config $wcConfig notion-bootstrap --parent-page '<Work-Context-page-URL-or-ID>' --apply --reviewed-hash '<review-hash-from-plan>'
```

The registry at the configured state directory's `notion-bootstrap.json`
records database and data-source IDs. Keep that file with the matching setup;
rerunning against it reuses known databases. If a creation response was
ambiguous, inspect Notion and reconcile the recorded pending operation before
retrying. Do not discard that registry to force another creation.

Now add the named views and page templates from the taxonomy document manually.
The API bootstrap creates the schema and default table views; it does not
install those named view or template UI objects. Create the first Project row,
the required BR/AC/CON rows, and the Work Item with the IDs from the local
contract. Notion relations and ownership fields are maintained in Notion.

## 5. Configure the inbound bridge

The source boundary is an explicit list of page IDs. Share only the intended
source pages with the read connection. Include the project brief page and every
required rule or acceptance row, or an existing standalone requirements page
with the ID headings in the supplied template. Referenced links and relation
targets are not captured automatically.

```powershell
python .\work-context.py --config $wcConfig configure-notion --page-id '<project-brief-page-ID>' --page-id '<BR-001-page-ID>' --page-id '<AC-001-page-ID>' --reviewed-scope
python .\work-context.py --config $wcConfig doctor
python .\work-context.py --config $wcConfig sync --task TASK-001
```

`--reviewed-scope` records the deliberate selection of the page scope on this
machine. It does not mean the page contents have been reviewed. After inspecting
the capture and packet, acknowledge the exact returned source hash and refresh:

```powershell
python .\work-context.py --config $wcConfig approve-source --reviewed-hash '<source_hash-from-sync>' --actor '<reviewer-name>'
python .\work-context.py --config $wcConfig sync --task TASK-001
```

The adapter requests full Markdown for the allowed pages, checks metadata for
concurrent edits, and refuses incomplete or unsupported required content. It
does not browse the rest of the Notion workspace or download attachments. A
Notion `Approved` label and the local source review are separate facts.

The local contract's `criteria_rules` must map each `AC-###` to its `BR-###` or
`CON-###` rules; use `rule_dependencies` for additional required IDs. The
compiler also includes dependencies declared in the captured row's structured
`Depends On IDs` property. Referenced pages still need to be allowlisted
explicitly. Confirm the mappings and source scope before refreshing; the
compiler cannot discover a forgotten dependency from prose.

## 6. Start and finish a normal task

At task start, update the local technical contract, verify its IDs against the
Notion Work Item, and refresh:

```powershell
python .\work-context.py --config $wcConfig sync --task TASK-001
python .\work-context.py --config $wcConfig status
python .\work-context.py --config $wcConfig packet --for cursor
```

Review freshness and review status separately. Resolve changed source reviews
before implementation. Cursor reads the returned packet and relevant project
files from the shared project wrapper. Confirm the small project rule appears
in the installed Cursor version. `.cursorignore` reduces accidental indexing of
notes and fixture inputs; it is not an operating-system access restriction.

When a Claude design or review pass is warranted, obtain the deliberate handoff:

```powershell
python .\work-context.py --config $wcConfig packet --for claude
```

Upload or paste only the returned `CLAUDE_PACKET.md` into the approved Claude
workspace through its normal interface. This kit does not connect or synchronize
Claude conversations and does not use a Claude API account. Record the task and
bundle IDs in the resulting proposal or review so its context remains traceable.

Run the actual project's reviewed tests through its established workflow.
Record the command, result, and evidence with the implementation. This kit does
not execute tests, protect a verification sandbox, or decide business acceptance.
The human Work Item owner updates Notion verification and acceptance fields from
real evidence. Code edits make the previous candidate stale; `sync` creates a
new packet while source review remains attached to the captured business content.

No polling or scheduler is installed. Refresh explicitly at task start and
before preparing an update. The tool cannot detect a Notion edit until the next
live read. A local `status` check evaluates the last capture age and local
changes; it is not a new server capture.

## 7. Prepare and optionally publish a reviewed update

After a fresh sync, create a local draft using your actual observations:

```powershell
python .\work-context.py --config $wcConfig draft-update --title 'TASK-001 mapping validation update' --summary '<actual outcome, check evidence, limitations, and next action>'
```

The result includes `draft_path`, the Markdown payload, and its hash. The
generated bridge observations explicitly say verification and business
acceptance have not been recorded by this bridge. A human-supplied summary is
not automatically trusted evidence.

Review the draft, then prepare the exact outbound payload using the
**Automation Updates data-source ID** from the bootstrap registry:

```powershell
python .\work-context.py --config $wcConfig publish --draft '<draft_path>' --data-source-id '<automation-updates-data-source-ID>'
```

This is a dry run. After reviewing the destination and content, apply its exact
`reviewed_operation_hash`:

```powershell
python .\work-context.py --config $wcConfig publish --draft '<draft_path>' --data-source-id '<automation-updates-data-source-ID>' --apply --reviewed-hash '<review-hash-from-plan>'
```

The publisher appends to Automation Updates. It does not update Requirements,
Work Items, Decisions, owners, deadlines, or business acceptance. Complete the
new update's Classification, Project, and Work Item relations manually; the
initial publisher does not infer them. Correct an update with a newly reviewed
draft and ID. Preserve the local publication journal to support safe retries.

## Troubleshooting and maintenance

| Observation | Meaning / next action |
|---|---|
| `NOT_CONFIGURED` | Set the explicit Notion page scope, or use a separately initialized demo vault. |
| Missing read credential | Provision `NOTION_READ_TOKEN` on the work machine using the approved mechanism; use `doctor` to check presence. |
| `REVIEW_REQUIRED` with `FRESH` | The source was captured successfully but that exact hash has no current local review acknowledgment. Inspect it, acknowledge the hash, then sync. |
| `STALE` | Capture age expired, or local code/task/brief changed. Run sync and inspect the new state. |
| `MISSING_REQUIREMENT` | A declared rule/criterion/dependency was absent. Fix source scope, exact IDs, or the reviewed contract. |
| `DUPLICATE_ID` | More than one captured section claims the same requirement. Keep one canonical body. |
| `INCOMPLETE` | Required content was truncated, unknown, unsupported, or otherwise incomplete. Fix the source structure or sharing; do not treat a previous packet as newly current. |
| `CONTEXT_TOO_LARGE` | Split the task or shorten an approved brief. Required rules are never silently removed to fit a budget. |
| `INTEGRITY` | A generated release was changed or is missing. Investigate the modified artifact; do not manually patch its manifest to silence the check. |
| `BOOTSTRAP_UNCERTAIN` / `WRITE_UNCERTAIN` | An external write outcome needs reconciliation. Inspect Notion and the journal before another write. |
| `BUSY` | Another command owns the project-state lock. Wait for it to finish, then retry. |

Keep repository code and reviewed technical documentation in the approved Git
workflow. Back up the non-Git vault notes and runtime state according to the
enterprise's policy. Credentials are provisioned independently. Do not place
the state registry into a personal sync folder or treat a copied config as a
portable connection: initialize paths and credentials afresh on the target
machine.

For the first pilot, record paid extra usage, accepted tasks completed before a
usage limit, and human preparation/review time. Include failed attempts. The kit
reduces repeated context assembly; its financial benefit must be measured in
the actual Claude/Cursor accounts and workload.
