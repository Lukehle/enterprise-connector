# Enterprise Connector

A portable bridge between your work Notion workspace, an Obsidian vault, and
project files used in Cursor. **Mac-first setup**, also tested on Windows and
Linux. Python 3.11+; no third-party runtime packages or LLM API account required.

[Download the portable kit](https://github.com/Lukehle/enterprise-connector/releases/latest)
• [Mac setup guide](docs/OPERATING_GUIDE.md)
• [Exact taxonomy](docs/TAXONOMY.md)
• [Notion setup](docs/NOTION_SETUP.md)
• [Readiness checklist](docs/WORK_MACHINE_CHECKLIST.md)
• [Review and boundaries](docs/REVIEW.md)

## What is built

| Bridge | Behavior |
|---|---|
| Setup → Obsidian/Cursor | Creates a shared vault/project structure, task and note templates, and a small Cursor rule; preserves existing files. |
| Setup → Notion | Plans and creates five collections, their properties and relations, and 12 named views; exports five Markdown templates. |
| Notion → context | Captures explicit page IDs, checks complete content and consistent revisions, and selects rules, acceptance criteria and declared dependencies. |
| Repository → context | Fingerprints configured files plus task scope, and includes the reviewed technical overview. |
| Context → Claude/Cursor | Produces compact versioned packets with source references, bounded size, freshness checks and independently stored manifest receipts. Claude handoff is manual. |
| Local outcome → Notion | Drafts and explicitly publishes summaries to the registered Automation Updates collection, with classification, optional relations, and durable duplicate checks. |
| Diagnostics and recovery | Offline self-test, read-only connection check, explicit damaged-packet repair, and reconciliation of uncertain Notion creates. |

The goal is to reduce repeated context assembly and wasted model turns. The
bridge makes **zero model calls**. It does not increase Claude/Cursor usage limits
or guarantee lower bills; measure extra usage and accepted work during a pilot.

## Exact organization

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

| Notion collection under Work Context | Stable IDs | Owns |
|---|---|---|
| Projects | PRJ-001 | Purpose, owner, lifecycle, repository and vault links |
| Requirements | BR-001 / AC-001 / CON-001 | Business rules, acceptance criteria and constraints |
| Work Items | TASK-001 | Intent, priority, human status and requirement relations |
| Decisions | BD-001 | Business decisions and references to technical ADRs |
| Automation Updates | UPD-… | Explicitly published outcome summaries |

Technical decisions remain `ADR-001` files in Git. Each system has an explicit
owner; the connector does not merge competing edits to the same requirement.

## Start on your work Mac

Extract the complete ZIP and open Terminal in the extracted `enterprise-connector`
folder. Use your work-approved Python 3.11 or newer:

```bash
python3 work-context.py self-test
bash scripts/Install-WorkContext.sh --vault "$HOME/Work/WorkVault" --project forecast-automation
```

This creates an **unconfigured** vault without contacting Notion. Runtime state
defaults to `~/Library/Application Support/WorkContext/<project>-<vault-hash>`.
Use the printed `config_path` for subsequent commands. Follow the
[operating guide](docs/OPERATING_GUIDE.md) to create and connect the Notion side.

To inspect a synthetic example first:

```bash
bash scripts/Install-WorkContext.sh --vault "$HOME/Work/WorkVault-Demo" --project forecast-automation --demo
wc_config="$HOME/Work/WorkVault-Demo/10 Projects/forecast-automation/context/config.json"
python3 work-context.py --config "$wc_config" sync
python3 work-context.py --config "$wc_config" packet --for cursor
```

Open the vault root in Obsidian. Open `10 Projects/forecast-automation` in Cursor.
They use the same local files; an Obsidian plugin is not required. The shell
scripts use the Bash shipped with macOS. [Windows wrappers](scripts/README.md)
are included. No installer downloads software or changes system policy.

## Verification and boundaries

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/package_kit.py
python3 scripts/verify_kit.py dist/enterprise-connector-v0.2.0.zip --smoke
```

CI runs the tests, offline self-test, archive verification, and extracted-kit
smoke test on macOS, Windows and Ubuntu with Python 3.11 and 3.14. HTTP tests use
simulated Notion responses; **live enterprise credentials and workspace access
must be verified on the work Mac**.

- Native Notion database templates are created manually from the exported
  Markdown. Initial business records and ownership remain human-maintained.
- A fresh packet and a local source-review acknowledgment are separate facts.
  Neither is protected enterprise authorization or evidence that code passed tests.
- This release provides the context bridges. It does not implement an execution
  sandbox, autonomous repair worker, deployment service or business acceptance.
- `status` checks the last capture, age and local files. Remote edits are detected
  by the next explicit `sync`. Default freshness is 15 minutes.
- Access loss and scope restrictions invalidate the pointer and quarantine old
  packets. A failed quarantine blocks capture until file access is resolved.
  Content already pasted into another application cannot be retracted.
- Local receipts protect against packet/manifest edits within the workspace;
  they are not cryptographic attestation against the same user editing local state.
- Tokens come only from `NOTION_READ_TOKEN` / `NOTION_WRITE_TOKEN` in the local
  process environment. Source caches, drafts and journals stay outside the vault.
  The credential-pattern guardrail is not a general secret scanner or DLP system.

Preserve write journals. An uncertain Notion response is reconciled against an
explicit candidate ID; deleting the journal and retrying can create duplicates.
