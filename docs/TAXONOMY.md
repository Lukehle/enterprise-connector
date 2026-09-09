# Exact Work Context taxonomy

Use one work-only Obsidian vault, one Notion parent page named **Work Context**,
and the five collections below. Obsidian and Cursor open the same physical
files. The bridge assembles selected approved context; it does not mirror every
Notion database into Markdown.

This kit is portable. On the enterprise work machine, use the company's approved
local path, for example `C:\Work\WorkVault`. Keep runtime state in the configured
application-data path, for example `%LOCALAPPDATA%\WorkContext`. Paths on the
computer that prepared the kit are not work-machine configuration.

## Vault folders and exact ownership

```text
WorkVault/                                      Obsidian opens this folder
├── 00 Home/
│   └── Home.md                                 starter project index
├── 01 Inbox/
│   ├── README.md
│   └── YYYY-MM-DD--topic.md                     unprocessed human notes
├── 10 Projects/
│   └── forecast-automation/                    Cursor opens this folder
│       ├── .cursor/
│       │   └── rules/00-work-context.mdc        small packet-loading rule
│       ├── .cursorignore
│       ├── repo/                               actual project Git repository
│       │   ├── src/
│       │   ├── tests/
│       │   ├── fixtures/                       synthetic setup material
│       │   ├── docs/
│       │   │   ├── AI_OVERVIEW.md               reviewed technical brief
│       │   │   └── adr/
│       │   │       └── ADR-001--decision-name.md
│       │   └── tasks/
│       │       └── TASK-001/
│       │           └── task.json               technical implementation contract
│       ├── notes/
│       │   ├── README.md
│       │   └── YYYY-MM-DD--topic.md             human working notes
│       └── context/
│           ├── config.json                     nonsecret bridge configuration
│           ├── START_HERE.md                   generated active-release pointer
│           ├── CURRENT_STATE.md                generated status projection
│           └── releases/
│               └── <bundle-id>/
│                   ├── AI_CONTEXT.md
│                   ├── CLAUDE_PACKET.md
│                   ├── CURSOR_TASK.md
│                   └── manifest.json
├── 20 Playbooks/
│   ├── README.md
│   └── PB-001--procedure-name.md                reviewed reusable human procedures
├── 90 Archive/
│   ├── README.md
│   └── <project-slug>/                          archived human notes
└── _templates/
    ├── inbox-note.md
    ├── project-note.md
    ├── playbook.md
    ├── technical-decision.md
    └── notion-requirements-page.md
```

The scaffold creates folders, README files, templates, the Cursor rule, the
technical overview, and the starter task. The bridge creates configuration and
generated context. Example note, playbook, and ADR filenames in the tree are
conventions, not fabricated work records. It does not run `git init` or clone a
repository. Attach the real project repository at `repo` through the normal
work-machine Git workflow.

| Location | Canonical owner | Permitted writer | Included in automatic packets? |
|---|---|---|---|
| Notion requirements and business decisions | Accountable business owner | Business owner and normal review process | Only explicitly captured, selected sections |
| `repo/src`, `repo/tests`, `repo/docs`, `repo/tasks` | Project repository | Normal reviewed development workflow | Allowlisted brief and technical contract; selected implementation fingerprints |
| `notes`, `01 Inbox` | Human author | Human author | No |
| `20 Playbooks` | Procedure owner | Human author/reviewer | No automatic discovery |
| `context/config.json` | Local setup owner | Setup commands and deliberate configuration edits | Configuration controls compilation; it is not business content |
| Other `context` files | Compiler projection | Bridge only | The selected immutable packet is the handoff |
| `00 Home/Home.md` | Local navigation | Scaffold once, then human maintenance | No |
| Application-data state | Local bridge | Bridge commands | No raw state dump or cache copied into packets |

Never place credentials, raw capture cache, local approval records, locks, or
the publication registry in the vault. The nonsecret config is the one explicit
exception to the generated-only `context` convention. Files outside the
workspace are organizationally separate; that alone does not restrict another
process running as the same user.

Scaffold reruns create missing files and preserve all existing content. In
particular, they do not rewrite your Cursor rules, edited templates, task
contracts, or Home page. Add the next project's Home link manually.

## Naming, identifiers, and frontmatter

Project folder slugs use lowercase words joined by hyphens, for example
`forecast-automation`. A slug is one folder name, not a path. Keep the slug
stable; rename only as an intentional migration of configuration and links.

| ID | Entity | Uniqueness / example |
|---|---|---|
| `PRJ-###` | Business project | Unique across Projects; `PRJ-001` |
| `BR-###` | Business rule | Unique across Requirements; `BR-001` |
| `AC-###` | Acceptance criterion | Unique across Requirements; `AC-001` |
| `CON-###` | Business constraint | Unique across Requirements; `CON-001` |
| `TASK-###` | Work item and matching technical task | Unique across Work Items; `TASK-001` |
| `BD-###` | Business decision | Unique across Decisions; `BD-001` |
| `ADR-###` | Technical decision | Unique inside its project; pair with `PRJ-001` when linking elsewhere |
| `PB-###` | Reusable procedure | Unique inside this work vault; `PB-001` |
| `UPD-<stable-id>` | Published update | Deterministic from the reviewed update; never manually reuse it |

Use at least three digits; expand beyond 999. Titles may change; IDs do not.
Do not reuse a retired ID. Notion's UUID identifies the page for API transport;
`External ID` identifies the business object in readable links and contracts.
The first scaffold uses `TASK-001`. Give additional projects' tasks the next
unused ID and match their folder, JSON `id`, Notion record, and selected task.

Daily notes use ISO dates and a descriptive topic, such as
`2026-09-09--mapping-review.md`. ADRs and playbooks use the ID plus two hyphens,
such as `ADR-003--mapping-key.md` and `PB-002--monthly-reconciliation.md`.

Frontmatter is for human navigation and metadata. The compiler does not treat
a frontmatter `approved` value as approval or automatically index these notes.

| Note type | Required frontmatter fields | Exact status values |
|---|---|---|
| Inbox | `type: inbox`, `status`, `created`, `project_id` (nullable), `sources` (list) | `inbox`, `processed` |
| Project note | `type: project-note`, `status`, `created`, `project_id`, `related_ids` (list), `sources` (list) | `working`, `resolved`, `archived` |
| Playbook | `type: playbook`, `id`, `status`, `created`, `owner`, `reviewed_by`, `reviewed_on`, `related_ids`, `sources` | `draft`, `reviewed`, `retired` |
| Technical decision | `type: adr`, `id`, `status`, `created`, `project_id`, `related_ids`, `sources` | `proposed`, `accepted`, `superseded`, `rejected` |

Use `YYYY-MM-DD` dates, quoted strings when needed, and `[]` for an empty list.
For a reviewed playbook, `owner`, `reviewed_by`, and `reviewed_on` must be filled;
`reviewed_by` and `reviewed_on` may be `null` while draft. Replace template date
placeholders before saving a real note. Home, README files, technical overviews,
task JSON, and generated files are exempt from this human-note frontmatter
convention. No frontmatter plugin is required.

## Notion collections

The machine-readable contract is
[`src/work_context/notion_schema.json`](../src/work_context/notion_schema.json).
The bootstrap creates these five databases under the selected **Work Context**
parent page. The listed `Status` fields are **Select** properties with the exact
options below, not Notion's special Status property. All relation properties
refer to the collection shown; they are human-maintained references.

Every collection has these four properties:

| Property | Notion type | Rule |
|---|---|---|
| `Name` | Title | Human-readable title, required by the operating convention |
| `External ID` | Rich text | Stable ID, required and unique in that collection |
| `Status` | Select | Exact collection-specific values below |
| `Classification` | Select | `Public`, `Internal`, `Confidential`, `Restricted` |

Classification labels describe the source. They do not themselves authorize a
storage location, model, integration, or data transfer. Complete the fields
according to the enterprise's actual policies.

### Projects

One row per business project. Status options: `Proposed`, `Active`, `On hold`,
`Complete`, `Archived`.

| Additional property | Type | Value / relationship |
|---|---|---|
| `Owner` | People | Accountable project owner |
| `Repository URL` | URL | Approved project Git location |
| `Vault Slug` | Rich text | Exact local folder slug, e.g. `forecast-automation` |

Page template headings, in order: **Purpose; Outcome and success measure; Scope;
Out of scope; Systems and approved data; Stakeholders; Linked requirements;
Links**. If the project row is captured as the task's brief, add a concise
`## Project brief` section containing the context needed for that task.

### Requirements

One row per rule, acceptance criterion, or constraint. Status options: `Draft`,
`In review`, `Approved`, `Superseded`.

| Additional property | Type | Value / relationship |
|---|---|---|
| `Type` | Select | `Rule`, `Acceptance`, `Constraint` |
| `Project` | Relation → Projects | Owning project |
| `Owner` | People | Business requirement owner |
| `Approved By` | People | Person who completed the business review |
| `Approved On` | Date | Business review date |
| `Depends On IDs` | Rich text | Comma-separated stable IDs, e.g. `BR-001, BR-004` |

Page template headings, in order: **Statement; Rationale; Inputs and definitions;
Examples; Edge cases; Acceptance check; Depends on; Change history**.

In `Statement`, repeat the External ID, Type, Status, Classification, and
dependency IDs when the page is used as a captured source. A rule row should
include `## BR-001 — Rule title`; an acceptance row should include
`## AC-001 — Acceptance title`. The adapter can also identify an individual row
from its `External ID` property. Explicit headings make exports easier to audit.
An acceptance statement names the rules it checks and the measurable result.

An existing standalone requirements page is also supported. Structure its body
using `_templates/notion-requirements-page.md` and explicitly allowlist that
page. Choose one canonical body for each rule; do not maintain a separately
editable copy in both a summary page and a Requirements row.

`Approved` is a business workflow label. The local bridge separately records
review of the captured content hash. Any changed content requires review of its
new hash. This local acknowledgment is not an authenticated enterprise approval
system and does not infer approval from a label or from an agent's statement.

### Work Items

One row per business work item. The same `TASK-###` identifies its repository
contract. Status options: `Backlog`, `Ready`, `In progress`, `Blocked`, `Review`,
`Done`, `Cancelled`.

| Additional property | Type | Value / relationship |
|---|---|---|
| `Project` | Relation → Projects | Owning project |
| `Requirements` | Relation → Requirements | Business rules, acceptance criteria, constraints |
| `Priority` | Select | `P0`, `P1`, `P2`, `P3` |
| `Owner` | People | Human task owner |
| `Due` | Date | Agreed due date |
| `Task Path` | Rich text | `repo/tasks/TASK-001/task.json`, relative to the project wrapper |
| `Verification` | Select | `Not run`, `Passed`, `Failed` |
| `Business Acceptance` | Select | `Pending`, `Accepted`, `Rejected` |

Page template headings, in order: **Outcome; Required requirement IDs; Scope;
Acceptance criteria; Repository task path; Open questions; Latest update**.

Notion owns the requested business outcome, priorities, ownership, and business
acceptance. Local `task.json` specifies implementation boundaries and the exact
IDs to compile. The bridge does not keep these two records automatically in
sync. A human deliberately creates or changes the contract and checks that its
IDs match the Work Item. Verification fields in Notion are human-maintained
summaries; link actual test evidence. A published update does not mark them passed.

### Decisions

Business decisions only. Status options: `Proposed`, `Accepted`, `Superseded`,
`Rejected`.

| Additional property | Type | Value / relationship |
|---|---|---|
| `Project` | Relation → Projects | Owning project |
| `Requirements` | Relation → Requirements | Affected business requirements |
| `Owner` | People | Decision owner |
| `Decided On` | Date | Decision date |
| `ADR IDs` | Rich text | Related technical IDs, e.g. `PRJ-001/ADR-003` |

Page template headings, in order: **Question; Decision; Alternatives considered;
Business rationale; Consequences; Affected requirement IDs; Related ADR IDs;
Supersedes**. When a decision changes a rule, update and review that canonical
rule. Link technical implementation choices to `repo/docs/adr`; do not create a
second technical decision log in Notion.

### Automation Updates

Append-only reviewed summaries. Status option: `Published`.

| Additional property | Type | Value / relationship |
|---|---|---|
| `Project` | Relation → Projects | Associated project |
| `Work Item` | Relation → Work Items | Associated work item |
| `Payload Hash` | Rich text | Hash of the reviewed publication payload |
| `Published At` | Created time | Notion-created timestamp |

Page template headings, in order: **Outcome; Changes; Verification evidence;
Limitations; Next action; Task and bundle IDs**. The publisher writes the reviewed
body plus Name, External ID, Payload Hash, and Status. It does not infer or set
Classification or relation fields; complete those manually when using the board.
It inserts new records and detects duplicate IDs; corrections use a new update.
It does not modify requirements, task status, owners, deadlines, or acceptance.

## Exact Notion views and templates

The bootstrap creates each database with its default table view. Create these
named views and page templates manually in Notion; this kit does not claim to
install views or template UI objects.

| Collection | View name | Layout | Filter / sort |
|---|---|---|---|
| Projects | Active Projects | Table | Status = Active |
| Projects | All Projects | Table | No filter |
| Requirements | Approved Requirements | Table | Status = Approved |
| Requirements | Needs Approval | Table | Status = In review |
| Requirements | Rules | Table | Type = Rule |
| Requirements | Acceptance Criteria | Table | Type = Acceptance |
| Work Items | Ready Queue | Table | Status = Ready |
| Work Items | Blocked | Table | Status = Blocked |
| Work Items | Needs Review | Table | Status = Review |
| Decisions | Accepted Decisions | Table | Status = Accepted |
| Decisions | Proposals | Table | Status = Proposed |
| Automation Updates | Recent Updates | Table | Published At descending |

Use the ordered page-template headings specified for each collection. Add
linked views filtered by `Project` inside an individual project page if useful;
these are views of the same collections, never duplicate databases.

## Exact routing into a packet

The route is:

```text
Work Item TASK-001 (human business intent)
    → repo/tasks/TASK-001/task.json (deliberate technical contract)
    → acceptance_ids: AC-001
    → criteria_rules: AC-001 → BR-001
    → rule_dependencies: BR-001 → required additional rule IDs, if any
    → explicitly allowlisted page captures containing those IDs
    + reviewed repo/docs/AI_OVERVIEW.md
    → context/releases/<bundle-id>/... immutable packet
```

The starter contract is:

```json
{
  "id": "TASK-001",
  "project_id": "PRJ-001",
  "title": "Validate the pilot context",
  "goal": "Implement the reviewed pilot requirements and satisfy AC-001.",
  "rule_ids": ["BR-001"],
  "acceptance_ids": ["AC-001"],
  "criteria_rules": {"AC-001": ["BR-001"]},
  "rule_dependencies": {},
  "allowed_files": ["src/**", "tests/**"],
  "non_goals": ["Do not change approved business requirements."]
}
```

Keep every acceptance-to-rule mapping explicit. `rule_dependencies` maps a rule
ID to the IDs needed to interpret it, for example
`{"BR-003": ["BR-001", "CON-001"]}`. The compiler follows both that local map
and the structured `Depends On IDs` metadata on captured Notion rows. All
dependencies must already be present in the explicit page allowlist; the bridge
does not fetch additional pages just because they are referenced. For a
standalone requirements page, declare dependencies in the local task map.
The compiler does not infer dependency relationships from prose or traverse
Notion relations. Missing required content blocks the packet; do not replace
the missing content with a model's guess.

| Notion collection | Local destination / use |
|---|---|
| Projects | Explicitly captured `Project brief` can supply packet purpose; no full project mirror |
| Requirements | Selected BR/AC/CON sections from configured page captures enter generated releases |
| Work Items | Manual business-intent input to `repo/tasks/<TASK-ID>/task.json`; board is not mirrored |
| Decisions | Links and approved requirements they affect; decision log is not automatically mirrored |
| Automation Updates | Optional destination for reviewed local drafts; no inbound mirror |

Notebook discoveries route from Inbox to project notes, then either to Notion
for business review or to reviewed repository documentation for technical facts.
A playbook becomes packet context only through explicit inclusion in a supported
reviewed repository source. Merely moving a note or adding a tag never makes it
authoritative or exposes it to the model.

No embedding index, model calls, Notion-wide search, implicit linked-page crawl,
Obsidian plugin, or duplicate Cursor copy is required for these bridges.
