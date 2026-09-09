"""Build a source-only portable archive; never include vaults, state, or secrets."""

from pathlib import Path
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / "dist" / "enterprise-connector-v0.1.0.zip"
output.parent.mkdir(exist_ok=True)
paths = [root / name for name in ("README.md", "pyproject.toml", "work-context.py")]
for directory in ("src", "tests", "docs", "scripts"):
    paths.extend(p for p in (root / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".json", ".md", ".ps1"))
manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in manifest:
        archive.write(root / name, "enterprise-connector/" + name)
    archive.writestr("enterprise-connector/FILE_MANIFEST.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    for name, expected in manifest.items():
        assert hashlib.sha256(archive.read("enterprise-connector/" + name)).hexdigest() == expected
sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix(".zip.sha256").write_text(sha256 + "  " + output.name + "\n", encoding="utf-8")
print(json.dumps({"archive": str(output), "files": len(manifest) + 1, "sha256": sha256, "integrity": "verified"}, indent=2))
