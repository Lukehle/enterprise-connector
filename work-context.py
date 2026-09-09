"""Run directly from the portable kit, without installing dependencies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from work_context.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
