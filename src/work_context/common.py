"""Small shared primitives. No credentials or model clients live here."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise BridgeError("INVALID_JSON", f"Cannot read JSON file: {path}") from exc


def atomic_text(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wc-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def contained(root: Path, path: Path) -> Path:
    """Resolve existing junctions and symlinks before permitting a path."""
    resolved_root = Path(root).resolve()
    resolved_path = Path(path).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise BridgeError("PATH_ESCAPE", "A configured path escapes its allowed directory.")
    return resolved_path


@contextmanager
def project_lock(state_dir: Path):
    """OS-released advisory lock: a crash cannot leave a permanent lock."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    stream = (state_dir / "project.lock").open("a+b")
    locked = False
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except (OSError, BlockingIOError) as exc:
            raise BridgeError("BUSY", "Another command owns this project's state lock.") from exc
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()
