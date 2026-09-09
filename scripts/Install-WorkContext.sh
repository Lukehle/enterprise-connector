#!/bin/bash
# Compatible with the bash 3.2 supplied by macOS. Uses an existing Python only.
set -euo pipefail

usage() {
  printf '%s\n' 'Usage: bash scripts/Install-WorkContext.sh --vault PATH [--project SLUG] [--project-id PRJ-001] [--state-dir PATH] [--python /approved/python3] [--demo] [--self-test] [--preflight-only]'
}

vault_path=''
project='forecast-automation'
project_id='PRJ-001'
state_dir=''
python_command='python3'
demo=0
self_test=0
preflight_only=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --vault|--project|--project-id|--state-dir|--python)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then printf 'Missing value for %s\n' "$1" >&2; exit 2; fi
      case "$1" in
        --vault) vault_path=$2;;
        --project) project=$2;;
        --project-id) project_id=$2;;
        --state-dir) state_dir=$2;;
        --python) python_command=$2;;
      esac
      shift 2;;
    --demo) demo=1; shift;;
    --self-test) self_test=1; shift;;
    --preflight-only) preflight_only=1; shift;;
    --help|-h) usage; exit 0;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2;;
  esac
done
if [ -z "$vault_path" ]; then usage >&2; exit 2; fi
kit_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
launcher="$kit_root/work-context.py"
if [ ! -f "$launcher" ]; then printf '%s\n' 'Keep this script inside the complete kit.' >&2; exit 1; fi
if ! command -v "$python_command" >/dev/null 2>&1; then
  printf '%s\n' 'Select an already-approved Python 3.11+ executable with --python.' >&2; exit 1
fi
"$python_command" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or newer is required.")'
# This preflight is deliberately read-only. init handles full profile validation.
"$python_command" - "$vault_path" "$state_dir" "$project" "$project_id" <<'PY'
import pathlib, re, sys
vault = pathlib.Path(sys.argv[1]).expanduser().resolve()
state = pathlib.Path(sys.argv[2]).expanduser().resolve() if sys.argv[2] else None
if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", sys.argv[3]) or not re.fullmatch(r"PRJ-\d{3,}", sys.argv[4]):
    sys.exit("Use a lowercase project slug and a PRJ-001 style project ID.")
for path in (vault, state):
    if path is not None and (path == pathlib.Path(path.anchor) or (path.exists() and not path.is_dir())):
        sys.exit("Choose dedicated vault and state directories, never a filesystem root or file.")
if state is not None and (state.is_relative_to(vault) or vault.is_relative_to(state)):
    sys.exit("Vault and state must be separate non-overlapping directories.")
PY
if [ -f "$kit_root/FILE_MANIFEST.json" ]; then
  "$python_command" "$kit_root/scripts/verify_kit.py" "$kit_root"
fi
if [ "$self_test" -eq 1 ]; then "$python_command" "$launcher" self-test; fi
if [ "$preflight_only" -eq 1 ]; then
  printf '%s\n' 'Preflight passed. No target vault or state directory was created.'
  exit 0
fi
arguments=("$launcher" init --vault "$vault_path" --project "$project" --project-id "$project_id")
if [ -n "$state_dir" ]; then arguments+=(--state-dir "$state_dir"); fi
if [ "$demo" -eq 1 ]; then arguments+=(--demo); fi
exec "$python_command" "${arguments[@]}"
