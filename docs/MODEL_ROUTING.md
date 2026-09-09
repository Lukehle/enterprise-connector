# Model routing and context costs

Enterprise Connector prepares bounded stage handoffs and records inspected outcomes. It automatically selects the next stage from those records. It does **not** launch Claude/Cursor, run tests, verify a provider bill, or enforce an operating-system sandbox. The company-managed client retains its permissions. A human records the actual model, test evidence, technical review, and final business acceptance separately.

## Requested routes

| Workflow | Plan | Build | After two failed candidates | Technical review | Business acceptance |
|---|---|---|---|---|---|
| Claude Code CLI | Opus 4.8 | Haiku | One Sonnet 5 recovery attempt | Opus 4.8 | Human business owner |
| Cursor | Opus 4.8 | Cursor Composer | Stop for human diagnosis | Opus 4.8 | Human business owner |

The first failed Haiku attempt returns to Haiku. The second selects Sonnet 5. A failed recovery stops. A successful recovery still goes to Opus review; rejection there stops too. A test-passing candidate rejected by Opus consumes one failed-candidate allowance, preventing an unlimited build/review loop. Cursor has the same two-candidate limit with no invented recovery model. Smaller tasks can complete with one plan, one build, and one review.

An authentication error, usage limit, unavailable model, network failure, or missing context is `blocked`, not `build-failed`. Diagnose that outside the build loop. An explicit `route-resume` can restore a blocked stage after a human documents the restored prerequisite; all failure counters and the approved plan are preserved. It cannot resume rejected, exhausted, or invalidated runs. There is no automatic retry or reset command. Reinitializing unchanged task/source scope returns the existing run, including its spent budget. Code edits and changing a profile file cannot buy another attempt. A revised task or business scope starts a new run and requires a new approved plan. Local records are editable by the same user and are an audit aid, not protected enterprise authorization.

## Pin the exact available models on the work Mac

Reference Claude API IDs checked against official documentation on 2026-09-09:

| Role | Requested model | Reference API ID |
|---|---|---|
| Planner/reviewer | Opus 4.8 | `claude-opus-4-8` |
| Builder | Haiku 4.5 | `claude-haiku-4-5-20251001` |
| Recovery | Sonnet 5 | `claude-sonnet-5` |

Opus 4.8 remains documented as a legacy model. Its exact ID preserves your requested version. Haiku 4.5 is the documented current Haiku pin; your original request left the Haiku version open. Enterprise gateways may use deployment IDs instead of API IDs. Check availability and the actual underlying model with the company account before filling the profile. [Opus 4.8](https://platform.claude.com/docs/en/models/opus-4-8/overview), [current models and IDs](https://platform.claude.com/docs/en/models/overview).

Do not use `opus`, `sonnet`, `auto`, `default`, or `opusplan` here. They do not pin this workflow: Anthropic's `opus` alias currently resolves to Opus 5, while `opusplan` switches to Sonnet execution. Claude Code can substitute a managed-policy default when a requested model is excluded. Check the startup model and `/model` selection; for a captured JSON result, inspect `modelUsage`. Stop if the actual model differs. Do not change company restrictions to make the route pass. [Claude Code model configuration](https://code.claude.com/docs/en/model-config).

For Cursor, run `agent --list-models` with the work account and inspect the editor model selector. Copy the exact Opus 4.8 identifier for planner/reviewer into the profile: the template deliberately leaves it blank instead of guessing the provider-specific slug. The documented Composer reference is `composer-2.5`, but its presence, tier, and pricing must be checked in your account. Set an available **Composer** variant explicitly; do not substitute Auto. The editor selection is manual, while prepared Cursor CLI commands pass `--model`. [Cursor CLI parameters](https://cursor.com/docs/cli/reference/parameters), [Composer 2.5](https://cursor.com/docs/models/cursor-composer-2-5).

The local profile must retain each `requested_model` label, set its exact `model_id`, and record `verified_at` with a timezone plus a short `verification_note`. A profile older than 30 days is refused when initializing a route. This attestation is not an API availability test. A gateway can still remap a deployment later; inspect the actual model every stage.

## Mac operating sequence

Run from the downloaded kit directory. `CONFIG` is your **local** project profile, not a file in the shared Google Drive vault. Keep routing files and evidence under local application support.

```bash
CONFIG="$HOME/Work/ExecutionWorkspace/10 Projects/forecast-automation/context/config.json"
PROFILE="$HOME/Library/Application Support/WorkContext/claude-models.json"
python3 work-context.py route-template --workflow claude --output "$PROFILE"
```

Edit the profile after checking work-account availability. For Cursor, use `--workflow cursor` and a separate profile. Then capture, review, and sync the exact task before initializing:

```bash
python3 work-context.py --config "$CONFIG" sync --task TASK-001
# Inspect the source and use its returned hash:
python3 work-context.py --config "$CONFIG" approve-source \
  --reviewed-hash HASH_FROM_SYNC --actor "Your name"
python3 work-context.py --config "$CONFIG" sync --task TASK-001
python3 work-context.py --config "$CONFIG" route-init \
  --task TASK-001 --workflow claude --models "$PROFILE"
python3 work-context.py --config "$CONFIG" route-next --run-id RUN_FROM_INIT
```

`route-next` returns `cwd`, an **argument array** (`argv`), a bounded Markdown `handoff_path`, and an `evidence_template`. Nothing executes. Inspect the handoff and launch the selected client explicitly from the returned `cwd` using those arguments. Do not paste JSON into a shell or use `eval`; quote individual arguments normally. All prepared model sessions are interactive, retaining normal permission prompts.

Claude planning/review arguments select the exact model, plan permission mode, and read/search tools. Build/recovery arguments add file editing and Bash with default permissions. Cursor planning uses `--mode plan`; review uses `--mode ask`; building selects the confirmed Composer ID in normal agent mode. An editor user can instead open the local project wrapper, choose the same pinned model and stage mode manually, and paste the returned handoff. The routing ledger cannot control Cursor's editor selector. Prepared commands do not set `--force`, bypass permissions, or use a fallback-model flag.

After the plan, save the reviewed plan as a concise Markdown report and record `plan-approved`. A plan approval is a human approval of that exact report. Its saved, hashed contents accompany all subsequent stages. Each build attempt should execute that plan's meaningful tests once and end with an explicit result. Do not let the builder perform an unlimited repair loop inside one recorded attempt.

After code changes, run `sync --task TASK-001` before recording. Use the **new** code hash from sync in your evidence. Save one JSON evidence file based on the returned template:

```json
{
  "run_id": "RUN_FROM_INIT",
  "step_id": "STEP-002",
  "outcome": "build-failed",
  "actual_model_id": "claude-haiku-4-5-20251001",
  "code_hash": "CODE_HASH_FROM_CURRENT_SYNC",
  "summary": "Required duplicate-key test failed; other planned tests passed.",
  "report_path": "test-report.md"
}
```

The report should identify the task/candidate, actual model, commands run, exit codes, assertions or test counts, observed failure, and any checks not run. For planning it is the actual approved plan; for Opus review it is the inspected review with findings; for acceptance it is the human's criterion-by-criterion result. For a blocked model substitution, use the actual observed ID (or `unavailable`) and explain why work stopped. Model exit code zero alone is never evidence that tests passed.

```bash
python3 work-context.py --config "$CONFIG" route-record \
  --run-id RUN_FROM_INIT --outcome build-failed \
  --evidence "$HOME/Library/Application Support/WorkContext/evidence.json" \
  --actor "Your name"
python3 work-context.py --config "$CONFIG" route-next --run-id RUN_FROM_INIT
```

If the returned reason is `BLOCKED`, `route-next` also returns a `resume_evidence_template`. Once access or the missing prerequisite is restored, save that template with `outcome: "prerequisite-restored"`, the actual check in its report, and the unchanged candidate hash. Run `route-resume --run-id RUN_FROM_INIT --evidence /local/path/resume-evidence.json --actor "Your name"` using the same launcher/config prefix. It rechecks freshness, task/source/policy, and the unchanged candidate before restoring the previous stage. It neither invokes the model nor replenishes attempts. A completed route is a historical result tied to its returned candidate bundle/code hash, not approval of later edits.

One result consumes one issued step; duplicate/stale step records are refused. The report and evidence are copied into private runtime state and hashed. Reports are limited to 16 KB each and the full handoff to 48 KB. The handoff embeds the approved plan, the latest report, and summaries/hashes for the last two recorded results. Older full reports remain in the private ledger; large test logs should be retained separately and summarized accurately. An oversized next handoff is rejected before progression is committed, so shorten the current report before recording again.

Refresh is deliberately separate from routing: no model turn is spent checking Notion. A fresh capture has a limited lifetime. Routing stops on known changes to business source, task, overview, policy, or compiler. Code changes during BUILD/RECOVERY are expected and do not reset counters. Code changes during planning, review, or acceptance invalidate that stage. Observed changes outside the declared allowed-file scope stop the route; this check covers the bridge's fingerprinted files, not all operating-system activity. No filesystem write restriction or genuine test runner is claimed.

## Reduce plugin and MCP drain

The shared vault serves humans. Notion owns approved business meaning. The bridge fetches explicit allowed pages without model calls, compiles only the selected requirement IDs, and emits one local task packet. Claude and Cursor read that packet plus relevant local code. They do not need to discover the entire shared vault, search Notion repeatedly, or carry meeting archives through every conversation. The private routing ledger supplies small stage-specific handoffs instead of resuming an ever-growing cross-model transcript.

Finance code comes from the local checkout of the company's Google Drive Git
project. Plan and review using the declared task, local diff and actual test
results. Record repository/project ID plus full base and candidate commit IDs
in the report; no GitHub PR is needed. A commit ID and the connector's code hash
are separate evidence fields. Refresh and routing do not fetch, push, merge or
run GitHub workflows. See [FINANCE_GIT.md](FINANCE_GIT.md).

For Claude, the prepared per-session arguments use `--strict-mcp-config` with a generated empty `mcpServers` object and `--disable-slash-commands`; they do not modify global settings. Managed MCP configuration remains authoritative. These flags reduce optional tools/skills for this session but do not promise that managed servers, plugins, hooks, memories, or required company instructions disappear. Keep required company policy enabled; review optional plugin settings in the approved project profile. Avoid bare/safe mode as a blanket cost workaround because it can also skip useful project instructions and hooks. [CLI controls](https://code.claude.com/docs/en/cli-reference), [managed MCP behavior](https://code.claude.com/docs/en/mcp).

For Cursor, review Settings → Tools & MCP and the configured project/global sources before the task. Enable only tools needed by this project; use the editor's per-tool/server controls where available. A blank project `.cursor/mcp.json` does **not** prove global servers are disabled. `agent mcp list` shows inherited configuration. The kit does not silently change global settings or call `--approve-mcps`. Confirm the effective tool list in the work client. [Cursor MCP](https://cursor.com/docs/context/mcp), [CLI MCP](https://cursor.com/docs/cli/mcp).

Modern clients can defer tool definitions, so savings are not simply “MCP count × schema tokens.” The main controllable waste is repeated retrieval, oversized results, unnecessary agents, long transcripts, and repeated failed implementation. Notion/Obsidian storage does not expand Claude/Cursor quotas or make expensive models free. [Claude Code cost guidance](https://code.claude.com/docs/en/costs).

Run a two-week pilot with comparable tasks: record task size, packet bytes/estimated tokens, actual model IDs, tool calls, paid/included usage from the vendor dashboard, failed candidates, recovery calls, elapsed time, and human rework. Compare cost per **accepted** task and limit-hit frequency against the previous workflow. Separate API charges from subscription usage. Haiku's lower price is useful only when total retries and review effort stay lower; the two-failure limit makes that tradeoff visible. Task planning and review may themselves dominate tiny edits, so measure whether batching a few related, low-risk edits under one scoped task is cheaper.
