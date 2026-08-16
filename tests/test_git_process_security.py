import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain import repository
from rta_brain.hooks import _cli_invocation


def _shell_command(*parts: Path | str) -> str:
    values = [str(part).replace("\\", "/") for part in parts]
    if sys.platform == "win32":
        return " ".join(f'"{value}"' for value in values)
    return " ".join(shlex.quote(value) for value in values)


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitProcessSecurityTests(unittest.TestCase):
    def _init_repository(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)

    def _write_probe(self, root: Path) -> Path:
        probe = root.parent / "hostile_git_probe.py"
        probe.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text('executed', encoding='utf-8')\n"
            "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
            encoding="utf-8",
        )
        return probe

    def test_repository_state_disables_hostile_fsmonitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            self._init_repository(root)
            probe = self._write_probe(root)
            marker = Path(tmp) / "fsmonitor-executed.txt"
            command = _shell_command(sys.executable, probe, marker)
            subprocess.run(["git", "-C", str(root), "config", "core.fsmonitor", command], check=True)

            state = repository.repository_state(root)

            self.assertTrue(state["is_git_repo"])
            self.assertFalse(marker.exists(), "repository inspection executed core.fsmonitor")

    def test_git_inspection_disables_hostile_clean_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            self._init_repository(root)
            (root / ".gitattributes").write_text("payload.txt filter=HostileCase\n", encoding="utf-8")
            (root / "payload.txt").write_text("safe\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", ".gitattributes", "payload.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)

            probe = self._write_probe(root)
            marker = Path(tmp) / "filter-executed.txt"
            command = _shell_command(sys.executable, probe, marker)
            subprocess.run(["git", "-C", str(root), "config", "filter.HostileCase.clean", command], check=True)
            subprocess.run(["git", "-C", str(root), "config", "filter.HostileCase.required", "true"], check=True)
            (root / "payload.txt").write_text("changed\n", encoding="utf-8")

            result = repository.run_git_inspection(
                root, "hash-object", "--path", "payload.txt", "payload.txt",
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "repository inspection executed a clean filter")

    def test_git_inspection_fails_closed_when_executable_config_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            self._init_repository(root)
            with patch("rta_brain.repository._configured_command_keys", return_value=None):
                self.assertIsNone(repository.run_git_inspection(root, "status", "--short"))

    def test_hook_cli_resolution_ignores_project_local_shadow_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = root / "rta_brain"
            shadow.mkdir()
            marker = root / "shadow-imported.txt"
            (shadow / "__init__.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
                encoding="utf-8",
            )
            invocation = shlex.split(_cli_invocation(), posix=True)

            result = subprocess.run(
                [*invocation, "--version"], cwd=root, capture_output=True, text=True, timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("rta-brain", result.stdout)
            self.assertFalse(marker.exists(), "hook imported a project-local shadow package")


if __name__ == "__main__":
    unittest.main()
