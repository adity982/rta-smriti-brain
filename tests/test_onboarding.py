import tempfile
import unittest
from pathlib import Path

from rta_brain.console_daemon import stop_console
from rta_brain.onboarding import derive_project_name, onboard_project
from rta_brain.watch_daemon import stop_watcher


ROOT = Path(__file__).resolve().parents[1]


def make_minimal_git_repo(root: Path) -> None:
    git_dir = root / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (git_dir / "refs" / "heads" / "main").write_text("a" * 40 + "\n", encoding="ascii")


class OnboardingTests(unittest.TestCase):
    def test_project_name_is_safe_and_deterministic(self):
        self.assertEqual(derive_project_name(Path("My Useful Project!")), "my-useful-project")
        self.assertEqual(derive_project_name(Path("...")), "project")

    def test_one_command_onboarding_uses_git_root_and_proves_runtime_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "My Product"
            nested = root / "src" / "feature"
            nested.mkdir(parents=True)
            make_minimal_git_repo(root)
            (root / "main.py").write_text("def ready():\n    return True\n", encoding="utf-8")
            brain_dir = Path(tmp) / "brains"

            payload = onboard_project(
                ROOT,
                nested,
                brain_dir=brain_dir,
                project=None,
                target_agent="universal",
                write_agents=False,
                port=0,
                open_browser=False,
                watcher_interval=0.2,
            )
            try:
                self.assertEqual(payload["status"], "ok")
                self.assertTrue(payload["ready"])
                self.assertEqual(payload["project"], "my-product")
                self.assertEqual(Path(payload["repo_path"]), root.resolve())
                self.assertTrue(Path(payload["db_path"]).is_file())
                self.assertEqual(payload["watcher"]["state"], "running")
                self.assertEqual(payload["console"]["state"], "running")
                self.assertTrue(payload["readiness"]["ready"])
                self.assertEqual([stage["state"] for stage in payload["stages"]], ["complete"] * 5)
                self.assertFalse((root / "AGENTS.md").exists())
            finally:
                stop_console(brain_dir, timeout=8.0)
                stop_watcher(Path(payload["db_path"]), payload["project"], timeout=8.0)

    def test_repeated_onboarding_reuses_the_existing_brain_incrementally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repeatable"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            brain_dir = Path(tmp) / "brains"
            first = onboard_project(
                ROOT, root, brain_dir=brain_dir, project="repeatable", port=0,
                open_browser=False, watcher_interval=0.2,
            )
            try:
                second = onboard_project(
                    ROOT, root, brain_dir=brain_dir, project="repeatable", port=0,
                    open_browser=False, watcher_interval=0.2,
                )
                self.assertTrue(second["ready"])
                self.assertEqual(second["db_path"], first["db_path"])
                self.assertEqual(second["bootstrap"]["ingest"]["updated_files"], 0)
                self.assertEqual(second["console"]["pid"], first["console"]["pid"])
            finally:
                stop_console(brain_dir, timeout=8.0)
                stop_watcher(Path(first["db_path"]), first["project"], timeout=8.0)


if __name__ == "__main__":
    unittest.main()
