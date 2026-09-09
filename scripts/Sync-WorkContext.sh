#!/bin/bash
# One explicit capture. No scheduler, token storage, package install or model call.
set -euo pipefail
config_path=''
python_command='python3'
task='TASK-001'
usage() { printf '%s\n' 'Usage: bash scripts/Sync-WorkContext.sh --config PATH [--task TASK-001] [--python /approved/python3]'; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --config|--task|--python)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then printf 'Missing value for %s\n' "$1" >&2; exit 2; fi
      case "$1" in --config) config_path=$2;; --task) task=$2;; --python) python_command=$2;; esac
      shift 2;;
    --help|-h) usage; exit 0;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2;;
  esac
done
if [ -z "$config_path" ] || [ ! -f "$config_path" ]; then printf '%s\n' 'Supply --config with the existing context/config.json.' >&2; exit 2; fi
kit_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
if ! command -v "$python_command" >/dev/null 2>&1; then printf '%s\n' 'Select an approved Python with --python.' >&2; exit 1; fi
exec "$python_command" "$kit_root/work-context.py" --config "$config_path" sync --task "$task"
