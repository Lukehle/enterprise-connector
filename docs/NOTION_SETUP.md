# Notion setup and recovery on the work Mac

The connector creates five databases, their relations, and twelve named views.
It exports five Markdown page templates and builds reviewed update publications
with explicit classification and project/task links. Perform these steps in the
approved enterprise workspace on the work machine.

The examples run from the extracted kit directory with Python 3.11 or newer.
Set `wcConfig` to the configuration printed by `init`:

```sh
wcConfig="$HOME/Work/WorkVault/10 Projects/forecast-automation/context/config.json"
python3 ./work-context.py --config "$wcConfig" doctor
```

## Credentials and selected access

Provision `NOTION_READ_TOKEN` through the work machine's approved credential
mechanism for the source connection. It needs read content access to the
explicitly selected pages. Provision `NOTION_WRITE_TOKEN` separately for setup
and publication. Tokens are read from the process environment, never persisted
in the vault or configuration. Do not enter their values in these commands or
include them in a task packet.

Setup needs read access and insert content capability on the selected **Work
Context** parent page and the created databases. The publisher reads the
Automation Updates schema and queries its External ID property before insertion;
therefore a connection with insert capability alone is insufficient. Explicit
Project and Work Item links also require read access to those selected relation
pages and their related databases. Select the intended access in Notion; the
connector never expands sharing or retries with a more privileged credential.

## Create the exact taxonomy

Create or select **Work Context** in Notion and copy its page URL or ID. Preview:

```sh
python3 ./work-context.py --config "$wcConfig" notion-bootstrap --parent-page '<Work-Context-page-URL-or-ID>'
```

Review the five schemas and destination. Apply using the returned
`reviewed_operation_hash`:

```sh
python3 ./work-context.py --config "$wcConfig" notion-bootstrap --parent-page '<Work-Context-page-URL-or-ID>' --apply --reviewed-hash '<reviewed_operation_hash>'
```

The local `notion-bootstrap.json` registry belongs to this project and parent
page. Keep it in the configured state directory. A repeat invocation validates
the database identities, parents, property types, select options and relation
targets before continuing. It never overwrites a changed Notion schema.
Additional unrelated properties are tolerated; changing a required property's
name, type, options, or relation target requires restoring the intended schema.
Registries from v0.1 with the same database schema are verified and upgraded
automatically; unrelated schema hashes are rejected.

Bootstrap creates empty collections. Create the actual Project, Requirements,
and Work Item records with their agreed external IDs and ownership in Notion.
Business records and approval labels are not synthesized by setup. See
[TAXONOMY.md](TAXONOMY.md) for exact fields and statuses.

## Install the twelve named views

```sh
python3 ./work-context.py --config "$wcConfig" notion-views
python3 ./work-context.py --config "$wcConfig" notion-views --apply --reviewed-hash '<reviewed_operation_hash>'
```

The first command is an offline plan. The second validates all registered
databases, then creates these views with the filters and sorts in the taxonomy:

| Database | Views |
|---|---|
| Projects | Active Projects; All Projects |
| Requirements | Approved Requirements; Needs Approval; Rules; Acceptance Criteria |
| Work Items | Ready Queue; Blocked; Needs Review |
| Decisions | Accepted Decisions; Proposals |
| Automation Updates | Recent Updates, newest first |

Default Table views remain. Matching existing named views are reused. A
different filter, sort, source, duplicate name, or missing previously registered
view stops setup so human changes are preserved. Correct the conflict in Notion
and preview again. `notion-views.json` records progress and uncertain writes.
Only views under the five registered databases are inspected, with a maximum
of 1,000 views per database. No linked-source workspace search occurs.

## Export and create native page templates

```sh
python3 ./work-context.py export-notion-templates --output "$HOME/Work/NotionTemplates"
```

This offline command writes `projects.md`, `requirements.md`, `work_items.md`,
`decisions.md`, and `automation_updates.md`. Existing edited files are preserved;
choose a fresh output directory to regenerate them.

In each Notion database, open the menu beside **New**, create a new database
template, and paste the corresponding Markdown sections. Set appropriate default
properties and replace the placeholders before using a record. The published
Notion API supports listing and applying existing database templates; native
template creation remains a step in the Notion app. These exports are starting
points, not approval evidence or populated business records.

## Check connections without saving source content

After configuring the explicit page allowlist:

```sh
python3 ./work-context.py --config "$wcConfig" connection-check
```

The check reads exactly those pages, including their Markdown, and rejects
incomplete captures or metadata changes during a read. The result contains IDs
and pass/fail status, not captured page content. It does not save a source
snapshot. A failed source check invalidates local health and, for access loss,
revokes source review and quarantines old packets. A schema-only check failure
does not revoke readable source context.

To additionally verify the registered parent, all five databases, and their
required properties using the read credential:

```sh
python3 ./work-context.py --config "$wcConfig" connection-check --include-bootstrap
```

Use that option only when the read connection has the intended access to the
registered setup. Without it, destination sharing is not required. A successful
read-only check does not prove insert capability, validate enterprise policy,
or authorize project execution. The actual bootstrap/publish operation checks
its own destination before writing.

## Publish explicitly linked updates

Prepare a draft after completing and reviewing the work:

```sh
python3 ./work-context.py --config "$wcConfig" draft-update --title 'Mapping validation completed' --summary 'Reviewed outcome and verification evidence.' --classification Internal --project-page-id '<Project-row-URL-or-ID>' --work-item-page-id '<Work-Item-row-URL-or-ID>'
python3 ./work-context.py --config "$wcConfig" publish --draft '<draft-path>' --data-source-id '<registered-Automation-Updates-data-source-ID>'
python3 ./work-context.py --config "$wcConfig" publish --draft '<draft-path>' --data-source-id '<registered-Automation-Updates-data-source-ID>' --apply --reviewed-hash '<reviewed_operation_hash>'
```

Classification and relation IDs participate in the draft's payload hash. Repeat
the relation flags to supply multiple explicit links, up to 25 per relation.
The publisher checks that each selected page is active and belongs to the
relation's target collection. It does not infer links from prose or publish
other task records. Use a new update ID for a correction; published updates are
never automatically rewritten.

Deduplication verifies the destination, External ID, recorded payload hash,
title, status, and supplied metadata. A remote payload-hash property is an
integrity marker, not a signed guarantee against a human editing the remote
Markdown body. The reviewed local draft remains the publication record.

## Recover from an uncertain network write

Writes are not automatically retried. A timeout can occur after Notion has
created the object. The local journal remains pending until its outcome is
verified. Do not delete or hand-edit journals to force a retry.

For an uncertain database create, find the created database under the selected
parent in Notion and copy its ID. Preview and apply reconciliation:

```sh
python3 ./work-context.py --config "$wcConfig" notion-reconcile --parent-page '<Work-Context-page-URL-or-ID>' --database-id '<created-database-URL-or-ID>'
python3 ./work-context.py --config "$wcConfig" notion-reconcile --parent-page '<Work-Context-page-URL-or-ID>' --database-id '<created-database-URL-or-ID>' --apply --reviewed-hash '<reviewed_operation_hash>'
```

This checks the pending payload, prior registered collections, candidate parent,
title, schema, and relation targets. Applying only adopts the verified IDs into
the local registry. Then rerun `notion-bootstrap` to finish the remaining
collections.

For an uncertain update publish, rerunning the same publish can reconcile an
indexed matching External ID. If the new page is visible in Notion but the
query still cannot find it, copy that exact page ID and run:

```sh
python3 ./work-context.py --config "$wcConfig" update-reconcile --draft '<draft-path>' --data-source-id '<registered-Automation-Updates-data-source-ID>' --page-id '<created-update-page-URL-or-ID>'
python3 ./work-context.py --config "$wcConfig" update-reconcile --draft '<draft-path>' --data-source-id '<registered-Automation-Updates-data-source-ID>' --page-id '<created-update-page-URL-or-ID>' --apply --reviewed-hash '<reviewed_operation_hash>'
```

These reconciliation previews perform reads, so they require the write
connection's read access. Applying updates the local outbox only; it never
creates, edits, or deletes a Notion page. If the candidate does not match the
pending intent, the journal remains unchanged.

For an uncertain view create, rerun `notion-views` once the view is visible. An
exact matching named view is adopted without another POST. If the object is
still absent, the command stops. When a write's outcome cannot be established,
retain its journal and investigate the original operation before creating a
replacement; query absence alone is not proof that creation failed.

## Verification scope and API references

The bridge is tested with a local in-memory transport for real documented
endpoint shapes, permission failures, schema drift, interrupted writes,
deduplication, classification/relation hashing, and bounded pagination. This kit
has not been connected to your enterprise workspace from the personal machine.
Run the connection checks and a synthetic pilot on the work machine before
capturing real project requirements.

API version: `2026-03-11`. Official references checked September 9, 2026:

- [Create a database](https://developers.notion.com/reference/create-database)
- [Retrieve a data source](https://developers.notion.com/reference/retrieve-a-data-source)
- [Create a view](https://developers.notion.com/reference/create-view)
- [List views](https://developers.notion.com/reference/list-views)
- [View object and filters](https://developers.notion.com/reference/view)
- [Create pages from existing templates](https://developers.notion.com/guides/data-apis/creating-pages-from-templates)
