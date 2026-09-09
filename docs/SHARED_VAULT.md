# Luke and Boss: shared Obsidian vault

Use one company Google Drive vault for working knowledge, one canonical Notion
workspace for business decisions, and a separate local code workspace on each
Mac. Enterprise Connector refreshes selected Notion context without asking an
AI model to browse the vault. The shared mirror is for people to read; Claude
and Cursor receive a separately validated local task packet.

## Storage and ownership

Prefer a company **Shared Drive** named by your organization, with a folder such
as `Work Together`. Shared Drive files belong to the organization and remain
when an individual leaves. If your organization instead supplies an ordinary
shared folder in My Drive, record its owner and an ownership-transfer plan.
Have your existing Drive administrator assign roles sufficient for the desired
edits and moves; this kit does not change Drive access. See Google's
[Shared Drive ownership and permissions](https://support.google.com/a/users/answer/7212025?hl=en).

On both Macs, use the approved Google Drive for desktop installation and choose
the actual vault location in Finder. **Shared Drives support streaming only.**
My Drive supports streaming or mirroring. Mark the entire vault **Available
offline**, wait for synchronization to finish, and keep Drive running during
work. Modern macOS File Provider configurations can access already-downloaded
files with Drive closed; this does not mean new changes are synchronizing.
See [streaming versus mirroring](https://support.google.com/drive/answer/13401938?hl=en)
and the [macOS and offline-access guide](https://support.google.com/drive/answer/16631477?hl=en).

Open that downloaded folder as an Obsidian vault. Google Drive is a third-party
sync arrangement described by Obsidian, rather than Obsidian's own supported
sync service. Use one sync provider for this vault and keep it downloaded;
Obsidian needs access to its files to resolve links. Do not add Obsidian Sync,
another Drive plugin, or a second cloud sync engine to the same folder. See
[Obsidian's synchronization guidance](https://help.obsidian.md/sync-notes).

Choose Obsidian **Settings → Files and Links → Override config folder**:

| Device | Config folder |
|---|---|
| Luke's work Mac | `.obsidian-luke-mac` |
| Boss's work Mac | `.obsidian-boss-mac` |

Relaunch Obsidian after changing it. This prevents both devices writing the
same settings files, but both folders remain inside the shared vault and are
readable by its members. They are **not private credential stores**. Keep the
initial setup to core plugins; the bridge does not install community plugins,
copy plugin secrets, or enable AI plugins. See
[Obsidian configuration folders](https://help.obsidian.md/configuration-folder).

Keep the following outside Google Drive, iCloud Desktop/Documents, and other
automatic cloud backup paths: local code checkout, `.git`, Cursor configuration,
Claude session state, task contracts, generated agent packets, connector
configuration, API credentials, review receipts, outbox, logs, and quarantine.
A suggested local workspace is `~/Work/ExecutionWorkspace`. Runtime
state defaults to `~/Library/Application Support/WorkContext/…`. These are
examples in the setup guide only; the shared scaffold contains no machine paths.
The initializer rejects overlap with the selected shared vault. It cannot
discover every folder your employer's sync software might also synchronize.

After installing the reviewed kit, Luke initializes first. Replace the shared
path with the actual Finder location; Google Drive paths vary by account and
macOS configuration:

```sh
python3 work-context.py init-shared \
  --shared-vault "/actual/company/Google Drive/Work Together" \
  --local-workspace "$HOME/Work/ExecutionWorkspace" \
  --project forecast-automation --project-id PRJ-001 \
  --member-id luke --publisher-id luke
```

After the shared files arrive, Boss runs the same command on Boss's Mac with
`--member-id boss`. Both local workspace arguments may use the same spelling:
each resolves on its own Mac. Boss joins the existing UUID/project registry;
Boss must not create a second unrelated vault or copy Luke's local config.
Use `--demo` only in a separate synthetic trial profile.

## Exact folder taxonomy

The scaffold creates the current year under Meetings. The names below are
literal except for `<project-slug>`, `<publication-id>`, and date placeholders.

```text
Work Together/                         # Google Drive Obsidian vault
├── 00 Home/
│   ├── Home.md                        # manually maintained project index
│   ├── Working Agreement.md           # ownership, promotion, conflict rules
│   ├── People.md                      # luke and boss roles
│   └── ID Register.md                 # allocator and stable ID reservations
├── 01 Inbox/
│   ├── README.md
│   ├── luke/
│   └── boss/
├── 02 Meetings/
│   ├── README.md
│   └── YYYY/                          # YYYY-MM-DD--topic--scribe.md
├── 10 Projects/
│   └── <project-slug>/                 # e.g. forecast-automation
│       ├── 00 Overview/
│       │   └── Project.md             # purpose, owners, canonical Notion links
│       ├── 10 Notes/
│       │   ├── README.md
│       │   ├── luke/
│       │   └── boss/
│       ├── 20 Proposals/
│       │   └── README.md
│       ├── 30 Handoffs/
│       │   └── README.md
│       └── 40 Published/              # generated; do not edit
│           ├── README.md
│           ├── CURRENT.md             # pointer; validate before relying on it
│           ├── current.json           # current hash, observation, expiry, epoch
│           └── snapshots/
│               └── <publication-id>/
│                   ├── NOTION_CONTEXT.md
│                   └── manifest.json
├── 20 Playbooks/
│   ├── README.md
│   └── PB-001--procedure.md            # create from template when needed
├── 30 Reference/
│   └── README.md                      # links and approved small attachments
├── 90 Archive/
│   ├── README.md
│   └── YYYY/<original-relative-path>/
├── _templates/
│   ├── note.md
│   ├── meeting.md
│   ├── proposal.md
│   ├── handoff.md
│   └── playbook.md
└── 99 System/
    ├── README.md
    └── shared-vault.json               # logical identities; no device paths
```

`CURRENT.md`, `current.json`, and snapshots appear after a reviewed publication.
Human example notes and playbooks are not generated as fake completed records.
The shared vault deliberately has no code repository or runtime context folder.
Each local workspace uses the project layout in [TAXONOMY.md](TAXONOMY.md).

## IDs, metadata, and organization rules

| Record | ID / filename | Canonical owner |
|---|---|---|
| Project | `PRJ-001`; lowercase stable slug | Notion Projects; shared registry maps its folder |
| Business rule | `BR-001` | Notion Requirements |
| Acceptance criterion | `AC-001` | Notion Requirements |
| Business constraint | `CON-001` | Notion Requirements |
| Work item | `PRJ-001/TASK-001` | Notion Work Items; Git stores its implementation contract |
| Business decision | `BD-001` | Notion Decisions |
| Technical decision | `PRJ-001/ADR-001` | Git `docs/adr` |
| Playbook | `PB-001--procedure.md` | Shared `20 Playbooks` |
| Note / proposal | `YYYY-MM-DD--topic--luke.md` or `--boss.md` | Corresponding shared member/project folder |
| Meeting | `YYYY/YYYY-MM-DD--topic--scribe.md` | Shared Meetings; one named scribe |
| Handoff | `YYYY-MM-DD--TASK-001--member.md` | Shared project Handoffs |

Luke initially allocates project IDs and changes the shared registry. Reserve
IDs before creating canonical records; do not allocate the next counter from
two offline devices. Project IDs are unique across the vault and are checked by
the scaffold. BR/AC/CON/BD/PB IDs should be unique within their canonical
registers across projects and never reused. TASK and ADR IDs are project-scoped:
always include the PRJ ID when citing them outside the project. The ID Register
is human-maintained; scaffold reruns preserve it and Home rather than silently
rewriting your edits. Add their new project entries during project onboarding.

Use lowercase hyphenated slugs and consistent ID casing. Do not create project
folders that differ only by case; Mac and Windows filesystems can differ in
case sensitivity. Do not rename a project slug after binding a local profile.
For a renamed display title, change the title in Project.md and Notion while
retaining the ID and folder slug.

Every note template has `type`, `status`, `owner`, `created`, `project_id`,
`classification`, `related_ids`, and `notion_url`. Set the owner to the member
who will edit the file. Classify before sharing. Use simple metadata fields
rather than accumulating synonymous tags. Optional tags describe a topic such
as `finance` or `reporting`; status and ownership remain structured fields.

Working notes use `working`; proposals use `draft → in-review → accepted` or
`rejected`. Playbooks use `draft → in-review → approved → retired`, and record
`reviewed_by`, `reviewed_on`, and `review_due`. Review playbooks every 90 days
and after a relevant business change. A proposal marked accepted is a recorded
outcome, not automatic approval of a Notion requirement.

## The Notion connection

Use the existing five Notion collections and their exact properties from
[TAXONOMY.md](TAXONOMY.md) and [NOTION_SETUP.md](NOTION_SETUP.md). Link them in each
shared Project.md rather than duplicating editable task tables in Obsidian.

| Information | Direction | Update rule |
|---|---|---|
| Purpose, priority, status, owner | Notion Projects → Project.md links | Humans maintain project overview; no automatic overwrite |
| Working observation | Member inbox → project notes | Capture and triage without AI |
| Proposed rule or change | Shared Proposal → human review → Notion Requirements | Boss approves canonical meaning in Notion |
| Approved BR/AC/CON context | Explicit Notion page allowlist → local capture → reviewed shared mirror | Connector reads only configured complete pages |
| Business decision | Meeting/proposal → Notion Decisions | Shared note records resulting BD ID and link |
| Action / delivery status | Notion Work Items ↔ reviewed update | Native task state remains human-owned |
| Technical implementation | Local Git → reviewed handoff | Share a small factual summary and Git link |
| Automation update | Local draft → exact reviewed destination/hash → Notion Automation Updates | Explicit publication; no background write-back |

There is no automatic bidirectional Markdown merge. Editing the shared mirror
does not edit Notion, and editing a proposal does not promote it into a rule.
Notion relations provide navigation; the connector does not recursively follow
every relation or Drive link. Only approved source scope enters the local
capture. Playbooks and meeting notes are excluded until required text is
explicitly promoted into a configured Notion source or reviewed Git brief.

Use separate read and write Notion credentials on the work machine, following
the existing setup guide. Boss can read shared publications without having a
Notion token in the connector. If Boss also uses an agent to implement work,
Boss needs a separate local source capture and review under that account's
access; the shared reading cache cannot substitute for those checks.

## Self-updating behavior and failure handling

The designated publisher runs the local `refresh` workflow. It captures Notion,
checks classification and completeness, compiles the selected task, and publishes
shared source context only when its exact source hash has a local review
acknowledgment. A changed source requires review again; polling does not invent
approval. Unchanged captures reuse the same snapshot and update the pointer's
observation and expiry. No LLM is called by capture, comparison, or publication.
See the [operating guide](OPERATING_GUIDE.md) for CLI commands and the optional
work-Mac schedule, and [SELF_UPDATE.md](SELF_UPDATE.md) for the reviewed launchd
schedule and optional macOS Keychain integration.

For a configured local project, these commands use its own local config:

```sh
CONFIG="$HOME/Work/ExecutionWorkspace/10 Projects/forecast-automation/context/config.json"
python3 work-context.py --config "$CONFIG" refresh --task TASK-001
python3 work-context.py --config "$CONFIG" shared-publish
python3 work-context.py --config "$CONFIG" shared-status
```

`refresh` already publishes when eligible; `shared-publish` is an explicit
manual retry after review. Follow the source-hash review step in the operating
guide when publication reports `REVIEW_REQUIRED`. Boss uses `shared-status`
without publishing. Exporting a reviewed schedule produces a launchd plist;
it does not silently install or start a job on either person's Mac.

Start with a five-minute refresh interval during the workday and a 15-minute
freshness budget; use a manual refresh before a planning/build/review handoff.
This interval is a suggested configuration, not evidence that a job has been
installed on your Mac. Sleeping or offline machines cannot refresh; the cache
expires. `shared-status` verifies the replica's pointer, snapshot, content hash,
publisher epoch, allowed classifications, and observation age. A FRESH result
means those **local files** validate. It cannot prove Drive has delivered the
latest remote edit or prove Notion has not changed since the last capture.

Drive may deliver the pointer before the snapshot. Validation then fails until
all required files arrive. Never treat a green-looking Markdown heading as a
health check. A source-access failure, classification change, or invalidation
first marks shared context unavailable and then moves generated snapshot bytes
to the publisher's private quarantine. Pending removal blocks another publish.
Only three snapshots are retained in the shared folder after changed
publications; older generated copies move to local quarantine. Review and purge
that private quarantine according to company retention rules. Human notes are
not moved by this process.

This is not distributed locking or instantaneous remote revocation. A device
offline during revocation can retain old downloaded files. Membership controls,
device management, and retention belong to company Drive and endpoint policy.
Hashes detect accidental transfer errors; users who can edit both shared
content and its hashes can replace them. A shared snapshot is neither a signed
enterprise approval nor execution permission.

The software package itself does not auto-update or download executable code.
Review a released kit and its checksum, install locally, run its self-test, and
refresh context after an upgrade.

## Daily routine and publisher handover

Luke checks Drive synchronization, triages his inbox, reads current Notion Work
Items, refreshes the local task context, and resolves any source-review request.
Boss captures notes in the boss folder, owns business priorities and approvals
in Notion, and reads the validated shared mirror when reviewing a proposal.
Before a meeting, choose one scribe. Afterwards, move decisions and actions to
Notion and link their IDs back into the meeting note. At the end of a task, Luke
writes a short handoff with actual check results; Boss records business
acceptance separately in Notion.

Once a week, jointly triage proposals, reconcile conflict copies, review stale
playbooks, and archive inactive notes. Use an independent company-approved
backup: synchronization propagates mistakes as well as edits. Avoid concurrent
editing of the same Markdown file; per-member folders reduce collisions but
do not provide real-time coauthoring or a merge service.

For a publisher handover:

1. Stop all refresh schedules on the old publisher's devices and let Drive
   finish syncing. Coordinate the handover while both people are online.
2. The current publisher reviews and applies the exact handover plan. This
   invalidates the existing mirror and increments the project publisher epoch.
3. Wait until both replicas show the new registry assignment and epoch.
4. The new publisher explicitly reruns shared initialization against their
   existing local workspace to rebind the observed epoch. Configure their own
   credentials, refresh, acknowledge the source hash, and publish.
5. Start the new publisher's schedule only after `shared-status` validates on
   both machines. Keep the old schedule stopped.

The current publisher obtains the handover hash before applying it:

```sh
python3 work-context.py --config "$CONFIG" shared-handover --publisher-id boss
python3 work-context.py --config "$CONFIG" shared-handover --publisher-id boss \
  --apply --reviewed-hash "EXACT_HASH_FROM_REVIEWED_PLAN"
```

The old device refuses writes once it observes the changed registry. An offline
old device cannot observe that change, so coordinating step 1 is essential.
Member labels and epoch checks are practical coordination guards, not
authentication. For more members or independently running publishers, replace
the file-backed coordinator with a server-enforced lease and controlled writer
identity before scaling this arrangement.

## How this reduces agent overhead

Obsidian handles notes and links locally; Drive synchronizes files; a small
deterministic process fetches allowlisted Notion pages. Claude and Cursor receive
one compact task packet with only the required BR/AC/CON IDs, the reviewed
technical brief, code scope, freshness, and source references. They do not need
to enumerate every vault folder or call Notion MCP repeatedly to reconstruct
the same background on every turn.

Keep the whole shared Drive vault outside the agent workspace and index. Enable
an MCP server or plugin only for a task that actually requires live information
or an explicit write. Start the builder with the approved plan and narrow local
packet; hand a concise diff and real verification evidence to the reviewer.
See [MODEL_ROUTING.md](MODEL_ROUTING.md) for the requested Claude and Cursor
routes, model availability checks, and the two-failure recovery rule.

The bridge avoids model calls for organization and refresh; it does not make
provider tool use free or guarantee a percentage saving. Compare successful
tasks, paid overage, input/output usage, retry counts, and MCP calls before and
after adopting it. A cheaper builder that repeatedly fails can cost more than
a stronger model on a small, well-scoped task.
