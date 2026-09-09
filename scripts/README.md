# Work-machine PowerShell entry points

These scripts belong to the portable kit. Transfer the complete kit to the separate work machine through your company's approved process, and run it from an approved enterprise terminal. Keep `scripts` beside `work-context.py` and `src`.

The machine needs an approved Python **3.11 or newer** runtime. The kit uses Python's standard library and needs no `pip` packages. The scripts do not download or install software, change PowerShell execution policy, configure a scheduler, or save credentials. Use directories your account can already write to; this workflow does not require an administrator shell. If company policy blocks script execution, use your company's normal approval or signing process; do not bypass it.

## Initialize a dedicated vault

Run from the kit directory. Choose a company-approved path; `C:\Work\WorkVault` is only an example. Use a new, dedicated vault directory for the pilot.

```powershell
.\scripts\Install-WorkContext.ps1 -VaultPath 'C:\Work\WorkVault' -Project 'forecast-automation'
```

To choose an explicit approved Python executable and a separate state directory:

```powershell
.\scripts\Install-WorkContext.ps1 -VaultPath 'C:\Work\WorkVault' -Project 'forecast-automation' -StateDir 'C:\Work\WorkContextState' -Python 'C:\Approved Python\python.exe'
```

`-Demo` adds synthetic pilot material. Use it only when you want the demo content:

```powershell
.\scripts\Install-WorkContext.ps1 -VaultPath 'C:\Work\WorkVault-Demo' -Project 'forecast-automation' -Demo
```

The installer checks the Python version and calls the kit's `init` command. The command prints the created configuration location. Follow the main kit documentation for the exact Notion schema, configuration fields, and explicit bridge commands.

`-ProjectId` defaults to `PRJ-001`. Give each additional project its own stable ID, for example `-Project 'month-end-reconciliation' -ProjectId 'PRJ-002'`. The ID must match that project's Notion records; the project slug controls its local folder name.

## Run one synchronization

Pass the configuration file reported by initialization. For the vault and project in the first example:

```powershell
.\scripts\Sync-WorkContext.ps1 -ConfigPath 'C:\Work\WorkVault\10 Projects\forecast-automation\context\config.json'
```

The wrapper calls `python work-context.py --config <path> sync` and returns its exit code. It does not create Notion databases or run the separate write/export workflow.

For an approved read integration, have your company's credential mechanism supply `NOTION_READ_TOKEN` in the process environment before running a read bridge. Supply `NOTION_WRITE_TOKEN` only for an explicitly chosen write bridge using its separate integration. Never save either token in these scripts, a configuration file, vault notes, command history, or chat. The sync wrapper does not populate or print either variable.

An enterprise subscription does not automatically grant an integration access to a Notion workspace. Configure the appropriate integration and access to the intended work pages through your organization's approved process. Follow company policy for storage, transfers, integrations, and credentials on the work machine.

## Optional scheduling

Start with explicit manual runs. If your team later wants scheduling, IT can configure its existing scheduler to invoke `Sync-WorkContext.ps1` with the absolute kit and configuration paths and an approved Python executable. Credentials must come from the company's credential mechanism in that scheduled process environment. The wrapper makes one call and exits; it does not install a scheduled task or keep a background process running.

## Troubleshooting

- **Python not found or too old:** pass `-Python` with an approved executable for Python 3.11 or newer.
- **Launcher not found:** restore the complete kit layout instead of copying a script alone.
- **Configuration not found:** use the actual file path printed by `init`.
- **Access denied:** use an approved writable location or the company's standard access request process.
- **Notion synchronization fails:** inspect the command's error, configuration identifiers, integration permissions, and process environment. Do not paste token values into logs or support messages.

The Python CLI can also be run directly from an approved terminal using the same arguments. See the main kit README for the full command workflow.
