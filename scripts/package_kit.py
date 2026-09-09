"""Build a reviewed source-only archive, never collecting arbitrary user files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import tomllib
import zipfile

from verify_kit import verify_archive

# Add paths deliberately during review. No recursive source/config collection.
ALLOWED_FILES = (
    ".gitignore", ".gitattributes", ".github/workflows/ci.yml", "README.md", "pyproject.toml", "work-context.py",
    "docs/TAXONOMY.md", "docs/OPERATING_GUIDE.md", "docs/WORK_MACHINE_CHECKLIST.md",
    "docs/REVIEW.md", "docs/NOTION_SETUP.md",
    "docs/SHARED_VAULT.md", "docs/MODEL_ROUTING.md", "docs/SELF_UPDATE.md", "docs/REVIEW_V03.md",
    "scripts/Install-WorkContext.ps1", "scripts/Sync-WorkContext.ps1",
    "scripts/Install-WorkContext.sh", "scripts/Sync-WorkContext.sh", "scripts/README.md",
    "scripts/package_kit.py", "scripts/verify_kit.py", "scripts/ci_monitor.cjs",
    "src/work_context/__init__.py", "src/work_context/__main__.py",
    "src/work_context/cli.py", "src/work_context/common.py", "src/work_context/core.py",
    "src/work_context/vault.py", "src/work_context/notion.py", "src/work_context/notion_schema.json",
    "src/work_context/notion_setup.py", "src/work_context/readiness.py",
    "src/work_context/shared.py", "src/work_context/routing.py", "src/work_context/refresh.py",
    "tests/test_cli.py", "tests/test_core.py", "tests/test_vault.py", "tests/test_notion.py",
    "tests/test_core_hardening.py", "tests/test_cli_setup.py", "tests/test_notion_setup.py",
    "tests/test_readiness.py",
    "tests/test_shared.py", "tests/test_routing.py", "tests/test_refresh.py", "tests/test_shared_cli.py",
)


def source_bytes(root: Path, name: str) -> bytes:
    path = root / name
    for part in (path, *path.parents):
        if part == root:
            break
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Refusing linked release input: {name}")
    if not path.resolve().is_relative_to(root) or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Release input is not a regular contained file: {name}")
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def build(root: Path, output_dir: Path | None = None) -> dict:
    root = root.resolve()
    version = tomllib.loads(source_bytes(root, "pyproject.toml").decode())["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+-]*)", version):
        raise ValueError("The project version is not safe for a release filename.")
    contents = {name: source_bytes(root, name) for name in sorted(ALLOWED_FILES)}
    runtime_version = re.search(rb'^__version__\s*=\s*[\'"]([^\'"]+)', contents["src/work_context/__init__.py"], re.M)
    if runtime_version is None or runtime_version.group(1).decode() != version:
        raise ValueError("pyproject.toml and runtime __version__ must match.")
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    contents["FILE_MANIFEST.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    destination = (output_dir or root / "dist").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"enterprise-connector-v{version}.zip"
    if output.is_symlink():
        raise ValueError("Refusing a linked archive output.")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(contents.items()):
            info = zipfile.ZipInfo("enterprise-connector/" + name, (2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if name.endswith(".sh") else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    result = verify_archive(output)
    checksum = output.with_suffix(".zip.sha256")
    if checksum.is_symlink():
        raise ValueError("Refusing a linked checksum output.")
    checksum.write_text(result["sha256"] + "  " + output.name + "\n", encoding="utf-8", newline="\n")
    return {**result, "version": version, "checksum_file": str(checksum)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(Path(__file__).resolve().parents[1], args.output_dir), indent=2))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
