# Work Mac readiness checklist

For the v0.3 shared workflow, also follow [SHARED_VAULT.md](SHARED_VAULT.md),
[SELF_UPDATE.md](SELF_UPDATE.md) and [MODEL_ROUTING.md](MODEL_ROUTING.md).
The download commands below refer to the published v0.2 release; use a complete
reviewed v0.3 kit when evaluating the new branch.

Use the kit in a company-approved folder with an existing Python **3.11 or newer**.
The Python bridge has no third-party runtime packages. An enterprise AI plan does
not supply Python, Notion integration access, or approval for a particular data flow.

## Verify the transferred kit

Download the versioned release ZIP and its checksum through your normal work
transfer process. Compare the ZIP checksum to the release record before extracting:

```bash
shasum -a 256 enterprise-connector-v0.2.0.zip
```

From the extracted `enterprise-connector` directory:

```bash
python3 scripts/verify_kit.py .
python3 work-context.py self-test
```

- [ ] The expected ZIP checksum matches the release record.
- [ ] The manifest check returns `integrity: verified`.
- [ ] The offline self-test returns `status: passed` and `file_manifest.status: verified`.

A Git checkout has no generated release manifest; its self-test reports
`not_present`. File hashes detect accidental modification and transport corruption.
They are not code signatures, protected enterprise approvals, or a sandbox.

## Check the local setup before creating it

Replace the example paths with approved locations. Keep runtime state outside the
vault and outside cloud-synchronized folders. The macOS default is under
`~/Library/Application Support/WorkContext/` with a separate profile per vault/project.

```bash
bash scripts/Install-WorkContext.sh \
  --vault "$HOME/Work/WorkVault" \
  --project forecast-automation \
  --self-test --preflight-only
```

This checks the runtime, inputs and transferred manifest and runs only disposable
synthetic work. `--preflight-only` creates no target vault or state directory. It
does not prove that all future filesystem writes will be permitted by the company.

```bash
bash scripts/Install-WorkContext.sh \
  --vault "$HOME/Work/WorkVault" \
  --project forecast-automation
```

- [ ] Initialization returns the intended absolute configuration, vault and state paths.
- [ ] Obsidian opens the vault; Cursor opens `10 Projects/forecast-automation`.
- [ ] The work profile uses the intended enterprise accounts and approved models.
- [ ] Local storage and any Obsidian/Notion sync settings follow your work policy.

## Connect the actual Notion workspace

Follow [Notion setup](NOTION_SETUP.md) and the [operating guide](OPERATING_GUIDE.md).
These account-specific checks must run on the work Mac; the public kit and CI use
synthetic content and mock APIs.

- [ ] The separate read and write integrations have only their intended page access.
- [ ] Tokens enter the process through the approved credential mechanism; no token is saved in a vault, Git, configuration file, script or command history.
- [ ] The read-only connection check reaches the selected pages and reports complete supported content.
- [ ] The schema plan shows the intended parent page and collections before creation.
- [ ] Explicitly applied writes appear in the intended work Notion workspace.
- [ ] A small synthetic Notion pilot completes capture, local review, Claude/Cursor packets and an explicitly reviewed outcome update.
- [ ] A second unchanged synchronization reuses the packet; a changed rule requires a new source review.

## Evidence and boundaries

The included self-test verifies synthetic initialization, capture, review, both
packets, immutable packet reuse, local outcome drafting, and stale-code refresh.
The test suite exercises additional error paths and mock Notion behavior. CI runs
the source and extracted portable archive on macOS, Ubuntu and Windows with Python
3.11 and 3.14; inspect the run for the exact commit you transferred.

This kit does not autonomously execute a project's code, protect acceptance tests
from the current user, authenticate enterprise approvals, deploy business changes,
or measure actual provider billing. Start the real pilot with reviewed execution
and track paid extra usage per accepted task before expanding the harness.
