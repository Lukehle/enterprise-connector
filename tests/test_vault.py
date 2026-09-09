import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from work_context.common import BridgeError
from work_context.vault import scaffold_vault


class VaultScaffoldTests(unittest.TestCase):
    def test_scaffold_has_shared_project_and_valid_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "WorkVault"
            result = scaffold_vault(vault)
            self.assertEqual(set(result), {"vault_path", "project_path", "repo_path", "task_path", "config_path"})
            self.assertTrue(all(Path(path).is_absolute() for path in result.values()))
            task = json.loads(Path(result["task_path"]).read_text(encoding="utf-8"))
            self.assertEqual(task["project_id"], "PRJ-001")
            self.assertEqual(task["rule_ids"], ["BR-001"])
            self.assertEqual(task["acceptance_ids"], ["AC-001"])
            self.assertFalse(Path(result["config_path"]).exists())
            self.assertTrue((vault / "00 Home" / "Home.md").is_file())
            self.assertTrue((Path(result["project_path"]) / ".cursor" / "rules" / "00-work-context.mdc").is_file())
            self.assertTrue((Path(result["project_path"]) / "context" / "releases").is_dir())

    def test_repeated_scaffold_preserves_existing_human_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "WorkVault"
            result = scaffold_vault(vault)
            edited = [
                vault / "00 Home" / "Home.md",
                vault / "_templates" / "project-note.md",
                Path(result["repo_path"]) / "docs" / "AI_OVERVIEW.md",
                Path(result["task_path"]),
                Path(result["project_path"]) / ".cursorignore",
            ]
            for path in edited:
                path.write_text("Human content\n", encoding="utf-8")
            scaffold_vault(vault)
            for path in edited:
                self.assertEqual(path.read_text(encoding="utf-8"), "Human content\n")

    def test_project_path_traversal_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "WorkVault"
            for slug in ("../escape", "..\\escape", "a/b", "a\\b", "C:\\outside", "/outside", "", "..", "CON"):
                with self.subTest(slug=slug), self.assertRaises(BridgeError):
                    scaffold_vault(vault, project_slug=slug)
            self.assertFalse(vault.exists())

    def test_invalid_project_id_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "WorkVault"
            with self.assertRaises(BridgeError):
                scaffold_vault(vault, project_id="PRJ-001\nInjected: true")
            self.assertFalse(vault.exists())

    def test_existing_link_cannot_write_outside_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            vault = base / "WorkVault"
            external = base / "external"
            vault.mkdir()
            external.mkdir()
            try:
                (vault / "10 Projects").symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError):
                if os.name != "nt":
                    self.skipTest("Directory symlinks are unavailable on this filesystem")
                # Windows junctions exercise the real resolve() boundary without
                # requiring administrator or Developer Mode symlink privileges.
                created = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(vault / "10 Projects"), str(external)],
                    capture_output=True, text=True, check=False,
                )
                if created.returncode:
                    self.skipTest("Windows directory junctions are unavailable on this filesystem")
            with self.assertRaises(BridgeError):
                scaffold_vault(vault)
            self.assertEqual(list(external.iterdir()), [])
            self.assertFalse((vault / "00 Home").exists())


if __name__ == "__main__":
    unittest.main()
