"""Verify release bytes and optionally smoke-test an archive in temporary storage.

Hashes detect changed files; they are not signatures or execution authorization.
Use an expected ZIP checksum from a separately trusted release record if available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import zipfile

PREFIX = "enterprise-connector/"
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024


def safe_name(name: str) -> bool:
    return (isinstance(name, str) and bool(name) and "\\" not in name and ":" not in name
            and not name.startswith("/") and not name.endswith("/")
            and not any(ord(char) < 32 or char in '<>"|?*' for char in name)
            and all(part not in ("", ".", "..") and not part.endswith((".", " "))
                    and part.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
                    for part in name.split("/")))


def manifest_shape(value: object) -> dict:
    if not isinstance(value, dict) or not value or len(value) > 500:
        raise ValueError("Expected a nonempty file-hash manifest of at most 500 entries.")
    folded = set()
    for name, sha in value.items():
        if not safe_name(name) or name == "FILE_MANIFEST.json" or name.casefold() in folded:
            raise ValueError("Unsafe or duplicated manifest path.")
        folded.add(name.casefold())
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid manifest SHA-256.")
    for required in ("work-context.py", "pyproject.toml", "src/work_context/__init__.py", "scripts/verify_kit.py"):
        if required not in value:
            raise ValueError(f"Required kit file missing from manifest: {required}")
    return value


def verify_archive(path: Path, expected_sha256: str | None = None) -> dict:
    if path.stat().st_size > MAX_TOTAL:
        raise ValueError("Archive exceeds the portable kit size limit.")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 is not None and (not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256) or sha256 != expected_sha256.lower()):
        raise ValueError("Archive SHA-256 does not match the supplied release checksum.")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) > 501 or len(set(names)) != len(names):
            raise ValueError("Archive contains duplicated members or too many files.")
        if sum(entry.file_size for entry in entries) > MAX_TOTAL:
            raise ValueError("Archive expands beyond the portable kit size limit.")
        for entry in entries:
            if (not entry.filename.startswith(PREFIX) or not safe_name(entry.filename[len(PREFIX):])
                    or entry.file_size > MAX_FILE or entry.flag_bits & 1
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)):
                raise ValueError("Archive contains an unsafe member, link or unsupported file.")
        manifest_name = PREFIX + "FILE_MANIFEST.json"
        if manifest_name not in names:
            raise ValueError("Archive has no FILE_MANIFEST.json.")
        manifest = manifest_shape(json.loads(archive.read(manifest_name)))
        if set(names) != {PREFIX + name for name in manifest} | {manifest_name}:
            raise ValueError("Archive members do not exactly match its manifest.")
        for name, expected in manifest.items():
            if hashlib.sha256(archive.read(PREFIX + name)).hexdigest() != expected:
                raise ValueError(f"File checksum mismatch: {name}")
        if archive.testzip() is not None:
            raise ValueError("Archive CRC verification failed.")
    return {"archive": str(path.resolve()), "files": len(manifest) + 1, "sha256": sha256, "integrity": "verified"}


def verify_directory(root: Path) -> dict:
    root = root.resolve()
    manifest_path = root / "FILE_MANIFEST.json"
    if manifest_path.is_symlink():
        raise ValueError("Refusing a linked manifest.")
    manifest = manifest_shape(json.loads(manifest_path.read_text(encoding="utf-8")))
    for name, expected in manifest.items():
        path = root.joinpath(*PurePosixPath(name).parts)
        for candidate in (path, *path.parents):
            if candidate == root:
                break
            info = candidate.lstat()
            if candidate.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Refusing linked kit file: {name}")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"Missing or unsafe kit file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"File checksum mismatch: {name}")
    return {"directory": str(root), "files": len(manifest), "integrity": "verified", "scope": "manifest-listed files"}


def smoke_archive(path: Path) -> dict:
    verified = verify_archive(path)
    test_count = 0
    with tempfile.TemporaryDirectory(prefix="enterprise-connector-archive-") as temporary:
        temp_root = Path(temporary)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(temp_root)
        kit = temp_root / "enterprise-connector"
        verify_directory(kit)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(kit / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        commands = [[sys.executable, "work-context.py", "self-test"],
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]]
        for command in commands:
            result = subprocess.run(command, cwd=kit, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=180)
            if result.returncode:
                raise ValueError(f"Extracted kit check failed ({' '.join(command[1:])}):\n{result.stdout}\n{result.stderr}")
            if command[-1] == "self-test":
                evidence = json.loads(result.stdout)
                if evidence.get("status") != "passed" or evidence.get("file_manifest", {}).get("status") != "verified":
                    raise ValueError("Extracted self-test did not prove manifest integrity and workflow success.")
            else:
                count = re.search(r"Ran (\d+) tests? in", result.stderr)
                if count is None or int(count.group(1)) == 0:
                    raise ValueError("Extracted test suite did not report any executed tests.")
                test_count = int(count.group(1))
    return {**verified, "extracted_self_test": "passed", "extracted_test_suite": "passed",
            "discovered_tests": test_count, "temporary_files": "removed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="ZIP archive or extracted kit directory")
    parser.add_argument("--sha256", help="Expected archive checksum from the release record")
    parser.add_argument("--smoke", action="store_true", help="Extract a verified ZIP and run its self-test and unit suite")
    args = parser.parse_args()
    try:
        if args.path.is_dir():
            if args.smoke or args.sha256:
                raise ValueError("--smoke and --sha256 require a ZIP archive.")
            result = verify_directory(args.path)
        else:
            result = verify_archive(args.path, args.sha256)
            if args.smoke:
                result = smoke_archive(args.path)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
