import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from work_context.common import BridgeError
from work_context.readiness import run_self_test, verify_file_manifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import package_kit
import verify_kit


class ReadinessTests(unittest.TestCase):
    def test_synthetic_workflow_never_reaches_network_or_default_user_state(self):
        from work_context import core
        created = []
        real_initialize = core.initialize

        def initialize(vault, project, state, *args, **kwargs):
            created.extend((Path(vault), Path(state)))
            return real_initialize(vault, project, state, *args, **kwargs)

        with patch("work_context.readiness.core.initialize", side_effect=initialize), \
                patch("work_context.core.default_state_dir", side_effect=AssertionError("No user state")), \
                patch("work_context.notion.NotionClient.call", side_effect=AssertionError("No network")):
            result = run_self_test()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(len(result["checks"]), 10)
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))

    def test_manifest_detects_modified_files_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ok.py").write_bytes(b"original\n")
            manifest = {"ok.py": hashlib.sha256(b"original\n").hexdigest()}
            (root / "FILE_MANIFEST.json").write_text(json.dumps(manifest))
            self.assertEqual(verify_file_manifest(root)["status"], "verified")
            (root / "ok.py").write_bytes(b"changed\n")
            with self.assertRaises(BridgeError) as error:
                verify_file_manifest(root)
            self.assertEqual(error.exception.code, "KIT_INTEGRITY")
            for unsafe in ("../outside", "/absolute", "folder\\file", "C:relative", "a//b"):
                (root / "FILE_MANIFEST.json").write_text(json.dumps({unsafe: "0" * 64}))
                with self.subTest(unsafe=unsafe), self.assertRaises(BridgeError):
                    verify_file_manifest(root)

    def test_missing_manifest_is_explicitly_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(verify_file_manifest(Path(temporary))["status"], "not_present")

    def test_self_test_cleans_up_after_failure(self):
        created = []
        real_temp = tempfile.TemporaryDirectory

        def temporary(*args, **kwargs):
            owned = real_temp(*args, **kwargs)
            created.append(Path(owned.name))
            return owned

        with patch("work_context.readiness.tempfile.TemporaryDirectory", side_effect=temporary), \
                patch("work_context.readiness.core.sync", side_effect=BridgeError("TEST", "synthetic failure")):
            with self.assertRaises(BridgeError):
                run_self_test()
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        self.files = (".gitignore", "work-context.py", "pyproject.toml", "src/work_context/__init__.py", "scripts/verify_kit.py")
        bodies = {".gitignore": "*.token\n", "work-context.py": "print('synthetic')\n",
                  "pyproject.toml": '[project]\nversion = "2.3.4"\n', "src/work_context/__init__.py": '__version__ = "2.3.4"\n',
                  "scripts/verify_kit.py": "# synthetic fixture only\n"}
        for name, body in bodies.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8", newline="\n")

    def build(self):
        with patch.object(package_kit, "ALLOWED_FILES", self.files):
            return package_kit.build(self.root)

    def test_packaging_is_deterministic_normalizes_crlf_and_excludes_unknown_files(self):
        (self.root / "scripts" / "private.json").write_text('{"company": "synthetic private fixture"}')
        first = self.build()
        first_bytes = Path(first["archive"]).read_bytes()
        (self.root / "work-context.py").write_bytes(b"print('synthetic')\r\n")
        second = self.build()
        self.assertEqual(Path(second["archive"]).name, "enterprise-connector-v2.3.4.zip")
        self.assertEqual(Path(second["archive"]).read_bytes(), first_bytes)
        with zipfile.ZipFile(second["archive"]) as archive:
            self.assertIn("enterprise-connector/.gitignore", archive.namelist())
            self.assertNotIn("enterprise-connector/scripts/private.json", archive.namelist())
            self.assertTrue(all(entry.date_time == (2020, 1, 1, 0, 0, 0) for entry in archive.infolist()))

    def test_mismatched_runtime_version_stops_release(self):
        (self.root / "src/work_context/__init__.py").write_text('__version__ = "9.9.9"\n')
        with self.assertRaisesRegex(ValueError, "must match"):
            self.build()

    def test_symlink_candidate_stops_release(self):
        target = self.root / "work-context.py"
        target.unlink()
        try:
            target.symlink_to(self.root / "scripts/verify_kit.py")
        except OSError:
            self.skipTest("Creating symlinks is unavailable to this account")
        with self.assertRaisesRegex(ValueError, "linked"):
            self.build()

    def test_verifier_rejects_wrong_sha_and_changed_bytes(self):
        result = self.build()
        archive_path = Path(result["archive"])
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_kit.verify_archive(archive_path, "0" * 64)
        altered = self.root / "altered.zip"
        with zipfile.ZipFile(archive_path) as original, zipfile.ZipFile(altered, "w") as replacement:
            for entry in original.infolist():
                replacement.writestr(entry, b"changed" if entry.filename.endswith("work-context.py") else original.read(entry.filename))
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_kit.verify_archive(altered)
        # Explicit failures must still run when Python assertions are disabled.
        process = subprocess.run([sys.executable, "-O", str(ROOT / "scripts/verify_kit.py"), str(altered)], capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)

    def test_verifier_rejects_traversal_extra_files_and_links(self):
        result = self.build()
        for name, mode in (("enterprise-connector/../../escape.py", stat.S_IFREG),
                           ("enterprise-connector/unlisted.py", stat.S_IFREG),
                           ("enterprise-connector/link", stat.S_IFLNK)):
            with self.subTest(name=name):
                altered = self.root / "extra.zip"
                shutil.copyfile(result["archive"], altered)
                with zipfile.ZipFile(altered, "a") as archive:
                    entry = zipfile.ZipInfo(name)
                    entry.external_attr = (mode | 0o644) << 16
                    archive.writestr(entry, "synthetic")
                with self.assertRaises(ValueError):
                    verify_kit.verify_archive(altered)


@unittest.skipUnless(os.name == "posix" and Path("/bin/bash").is_file(), "macOS/Linux bash wrapper test")
class MacShellTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="enterprise-wrapper-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.vault = self.root / "Vault with spaces $literal"
        self.state = self.root / "Separate State"
        self.install = ["/bin/bash", str(ROOT / "scripts/Install-WorkContext.sh"), "--vault", str(self.vault),
                        "--state-dir", str(self.state), "--python", sys.executable, "--project", "shell-check"]

    def run_ok(self, args):
        process = subprocess.run(args, cwd=self.root, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return process.stdout

    def test_preflight_only_does_not_create_target_directories(self):
        result = self.run_ok(self.install + ["--self-test", "--preflight-only"])
        self.assertIn("Preflight passed", result)
        self.assertFalse(self.vault.exists())
        self.assertFalse(self.state.exists())

    def test_demo_init_sync_and_nondefault_task(self):
        self.run_ok(self.install + ["--demo"])
        config = self.vault / "10 Projects/shell-check/context/config.json"
        repo = self.vault / "10 Projects/shell-check/repo"
        task = json.loads((repo / "tasks/TASK-001/task.json").read_text())
        task["id"] = "TASK-002"
        (repo / "tasks/TASK-002").mkdir()
        (repo / "tasks/TASK-002/task.json").write_text(json.dumps(task))
        sync = ["/bin/bash", str(ROOT / "scripts/Sync-WorkContext.sh"), "--config", str(config),
                "--python", sys.executable, "--task", "TASK-002"]
        result = json.loads(self.run_ok(sync))
        self.assertEqual(result["state"], "FRESH")
        self.assertEqual(result["task_id"], "TASK-002")

    def test_bad_overlap_fails_before_writes(self):
        args = self.install.copy()
        args[args.index("--state-dir") + 1] = str(self.vault / "nested-state")
        process = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(self.vault.exists())


@unittest.skipUnless(os.name == "nt", "Windows PowerShell wrapper test")
class WindowsShellTests(unittest.TestCase):
    def test_preflight_and_nondefault_task_preserve_exit_status(self):
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            self.skipTest("PowerShell executable unavailable")
        with tempfile.TemporaryDirectory(prefix="enterprise-ps-wrapper-") as temporary:
            root = Path(temporary)
            vault, state = root / "Vault with spaces", root / "Separate State"
            install = [executable, "-NoProfile", "-File", str(ROOT / "scripts/Install-WorkContext.ps1"),
                       "-VaultPath", str(vault), "-StateDir", str(state), "-Python", sys.executable,
                       "-Project", "shell-check"]
            preflight = subprocess.run(install + ["-SelfTest", "-PreflightOnly"], capture_output=True, text=True)
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            self.assertFalse(vault.exists())
            self.assertFalse(state.exists())
            initialized = subprocess.run(install + ["-Demo"], capture_output=True, text=True)
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            repo = vault / "10 Projects/shell-check/repo"
            task = json.loads((repo / "tasks/TASK-001/task.json").read_text())
            task["id"] = "TASK-002"
            (repo / "tasks/TASK-002").mkdir()
            (repo / "tasks/TASK-002/task.json").write_text(json.dumps(task))
            config = vault / "10 Projects/shell-check/context/config.json"
            sync = [executable, "-NoProfile", "-File", str(ROOT / "scripts/Sync-WorkContext.ps1"),
                    "-ConfigPath", str(config), "-Python", sys.executable, "-Task", "TASK-002"]
            synced = subprocess.run(sync, capture_output=True, text=True)
            self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)
            self.assertEqual(json.loads(synced.stdout)["task_id"], "TASK-002")
            missing = subprocess.run(sync[:-1] + ["TASK-999"], capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)


if __name__ == "__main__":
    unittest.main()
