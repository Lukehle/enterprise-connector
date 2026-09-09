# Finance Git in Google Drive

The confirmed finance setup is a **working project folder and its `.git` folder
both synchronized through company Google Drive**. Enterprise Connector works
with a separate local checkout of those projects. The public GitHub
repository distributes and tests this generic kit; finance work needs no GitHub
account, GitHub MCP, pull request or hosted CI. Run project checks locally and
record review in Notion with the candidate's Git identity.

## Storage map

Keep the existing finance Git folder and its naming unchanged. This example
shows separate roles, not a command to relocate company files:

```text
Company Google Drive/
  <existing finance project>/              shared working files and .git
  Work Together/                           shared Obsidian notes and reading cache

Each work Mac, outside Drive/
  Work/ExecutionWorkspace/
    10 Projects/<slug>/
      repo/                                local finance checkout, including .git
      .cursor/                             local project rules
      context/                             local config and generated packets
  Library/Application Support/WorkContext/  local receipts, routing, logs and state
```

The `repo` directory must be inside its local project wrapper. Changing
`repo_path` to an arbitrary external Drive folder is not an attachment feature.
The scaffold rejects overlap between local execution/state and the selected
shared Obsidian vault. It cannot discover every folder another sync client uses.

## Identify the existing arrangement

The shared working-repository arrangement is confirmed. Record its exact project
location, default branch and transfer owner during setup. The bare-repository
row below is a reference for a different project, not an assumption about this
one. Repository paths below are local Finder paths, not Drive web sharing URLs.
These inspection commands do not fetch or write:

```bash
finance_git='<existing repository path on this Mac>'
git -C "$finance_git" rev-parse --is-bare-repository
git -C "$finance_git" rev-parse --show-toplevel  # working repository only
```

| Existing arrangement | Connection to this kit |
|---|---|
| Bare repository in Drive; each person has a local clone | Keep the company's transfer procedure. Put the connector's local checkout at the wrapper's `repo`; keep the Drive remote path in that checkout's local Git configuration. |
| A working project and its `.git` both synchronize through Drive | Treat that as the existing company arrangement. Two people editing that shared checkout is outside this kit's validated execution layout; prepare an independent local checkout through a reviewed company transfer. |
| Repository form unknown | Inspect it with the repository owner. The Notion/Obsidian taxonomy can be set up independently; do not invent a clone URL or push target. |

Git explicitly advises against cloud-syncing any part of a repository because
individual files can arrive inconsistently and corrupt objects or refs. This
applies to bare repositories too. A single writer and waiting for Drive reduce
overlap but do not turn its replicas into a transactional Git server. Preserve
the existing repository and follow the team's approved transfer process; this
kit does not migrate it or certify its storage method.
[Git's transfer guidance](https://git-scm.com/docs/gitfaq#_transfers).

## Place the local checkout before initialization

Use an empty local destination. With an existing approved, fully available
filesystem source, the repository owner can clone before initializing the
connector. Stop source mutations and follow the existing sync/transfer procedure
first; this example does not establish that a Drive replica is current:

```bash
finance_source='<approved local filesystem source path>'
workspace="$HOME/Work/ExecutionWorkspace"
project_wrapper="$workspace/10 Projects/forecast-automation"
mkdir -p "$project_wrapper"
git clone --no-local -- "$finance_source" "$project_wrapper/repo"
git -C "$project_wrapper/repo" fsck --full
git -C "$project_wrapper/repo" rev-parse HEAD
# Compare the full commit ID with the repository owner's intended commit.
```

`--no-local` uses normal Git transport instead of the local hardlink/direct-copy
optimization; it does not fix cloud synchronization. A Drive HTTPS folder
sharing link is not a Git transport endpoint. `fsck` checks local Git integrity,
not whether the intended latest revision has arrived. A clone transfers committed
history, not another person's uncommitted work. Keep that work in its original
location until the owner deliberately records/transfers it.
[Git clone options](https://git-scm.com/docs/git-clone).

Cloning a working repository normally records that source as `origin`; it does
not authorize pushing into its checked-out branch. Return the reviewed candidate
through the finance repository owner's established integration process. Do not
relax receive settings or automate a push into the shared working directory to
bypass that process. Uncommitted work requires a separate deliberate handoff.

Then run `init-shared` from the kit with that same workspace and slug as shown in
[SHARED_VAULT.md](SHARED_VAULT.md). Existing project files are preserved; missing
technical overview/task templates are added for deliberate review. For an
already initialized `repo`, use a new empty local workspace or reconcile starter
files with the owner. Do not delete a nonempty directory to force a clone.

## Review and handoff without GitHub

Use the existing Notion Projects `Repository URL` property for the company Drive
folder sharing URL. In the project's **Links** section, record the relative
Drive location, repository form, default branch and Git transfer owner. The
shared Project note links to this row. Absolute Mac paths remain local.

A technical review or handoff records:

- Project/repository ID and `PRJ-001/TASK-001` business work-item reference.
- Branch/ref, full base commit ID and full candidate commit ID.
- Connector bundle ID and code fingerprint, separately from Git commit IDs.
- Actual test commands/results, reviewer findings and unresolved changes.
- Drive repository or transfer-artifact link; Notion acceptance record.

Review the local diff between those commits. Also disclose staged, unstaged and
untracked changes: a commit ID does not identify uncommitted candidate content.
The router records inspected evidence and a local file fingerprint; it does not
automatically capture Git commits or verify remote synchronization. Business
acceptance remains separate from the technical review. The finance Git transfer
owner and the shared-context publisher are distinct roles, even if both are Luke.

Claude and Cursor read the local packet and relevant local code. Neither needs
to browse the Drive Git internals or call GitHub tools. After a deliberate code
update, run `sync`/`refresh` before the next routing stage. The five-minute Notion
refresh job never performs Git fetch, pull, push, merge or maintenance.

## Optional Drive transfer artifacts

If the team wants a file-based transfer that avoids synchronizing live Git
internals, Git bundles are an option to review with the repository owner. Create
a finalized, uniquely named bundle locally, then copy that completed artifact
to a separate Drive transfer folder. Have the recipient download it locally,
compare its expected checksum and verify it before fetching or cloning.

Bundles support offline clone/fetch; they are not push destinations. Review the
included refs and history because an export can contain older sensitive commits.
They do not include uncommitted files or serve as a complete backup of repository
settings, hooks and working state. A checksum sent beside the bundle detects
transfer errors, not who approved it. The kit does not export bundles or change
the existing transfer method automatically.
[Git bundle documentation](https://git-scm.com/docs/git-bundle).
