import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rta-brain.py"


def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(CLI), *args], text=True, capture_output=True, cwd=cwd or ROOT)


class RtaBrainProjectUsabilityTests(unittest.TestCase):
    def test_bootstrap_project_creates_brain_indexes_repo_and_writes_agent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "demo-repo"
            repo.mkdir()
            (repo / "main.py").write_text("def memory_gate():\n    return 'fresh'\n", encoding="utf-8")
            brain_dir = Path(tmp) / "brains"

            result = run_cli(
                "--json",
                "bootstrap-project",
                str(repo),
                "--project",
                "demo",
                "--brain-dir",
                str(brain_dir),
                "--write-agents",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(Path(payload["db_path"]).exists())
            self.assertGreaterEqual(payload["ingest"]["indexed_files"], 1)
            self.assertTrue((repo / "AGENTS.rta-smriti.md").exists())
            self.assertTrue((repo / "AGENTS.md").exists())
            self.assertIn("Rta-Smriti Local Brain", (repo / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("agent_index_file", payload)
            self.assertIn("context-pack", payload["next_commands"]["context_pack"])

            self_check = run_cli("--db", payload["db_path"], "--json", "self-check", "--project", "demo")
            self.assertEqual(self_check.returncode, 0, self_check.stderr)
            health = json.loads(self_check.stdout)
            self.assertTrue(health["ready"])
            self.assertGreaterEqual(health["sources"], 1)
            self.assertEqual(health["freshness"]["mode"], "summary")

            self_check_full = run_cli("--db", payload["db_path"], "--json", "self-check", "--project", "demo", "--check-files")
            self.assertEqual(self_check_full.returncode, 0, self_check_full.stderr)
            full_health = json.loads(self_check_full.stdout)
            self.assertEqual(full_health["freshness"]["mode"], "file-hash")
            self.assertEqual(full_health["freshness"]["changed"], 0)

    def test_projects_list_reports_registered_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            init = run_cli("--db", str(db), "init", "--project", "demo", "--root", tmp)
            self.assertEqual(init.returncode, 0, init.stderr)
            result = run_cli("--db", str(db), "--json", "projects-list")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["projects"][0]["name"], "demo")

    def test_bootstrap_refuses_agent_file_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "linked-repo"
            repo.mkdir()
            (repo / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            victim = Path(tmp) / "victim.md"
            victim.write_text("keep me", encoding="utf-8")
            try:
                (repo / "AGENTS.md").symlink_to(victim)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            result = run_cli(
                "--json", "bootstrap-project", str(repo), "--project", "linked",
                "--brain-dir", str(Path(tmp) / "brains"), "--write-agents",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep me")
            self.assertFalse((repo / "AGENTS.rta-smriti.md").exists())

    def test_bootstrap_refuses_hard_linked_agent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "hard-linked-repo"
            repo.mkdir()
            (repo / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            victim = Path(tmp) / "victim.md"
            victim.write_text("keep me", encoding="utf-8")
            try:
                (repo / "AGENTS.md").hardlink_to(victim)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            result = run_cli(
                "--json", "bootstrap-project", str(repo), "--project", "linked",
                "--brain-dir", str(Path(tmp) / "brains"), "--write-agents",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep me")
            self.assertFalse((repo / "AGENTS.rta-smriti.md").exists())

    def test_bootstrap_refuses_hard_linked_brain_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            brain_dir = Path(tmp) / "brains"
            brain_dir.mkdir()
            victim = Path(tmp) / "victim.sqlite"
            victim.write_text("keep me", encoding="utf-8")
            (brain_dir / "demo.sqlite").hardlink_to(victim)
            result = run_cli("--json", "bootstrap-project", str(repo), "--project", "demo", "--brain-dir", str(brain_dir))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hard-linked brain database", result.stderr)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep me")

    def test_install_local_creates_wrappers_that_work_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bin"
            result = run_cli("--json", "install-local", "--target", str(target))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            wrapper = target / "rta-brain.cmd"
            mcp_wrapper = target / "rta-brain-mcp.cmd"
            self.assertTrue(wrapper.exists())
            self.assertTrue(mcp_wrapper.exists())

            doctor = subprocess.run(
                [str(wrapper), "--db", str(Path(tmp) / "brain.sqlite"), "--json", "doctor"],
                text=True,
                capture_output=True,
                cwd=tmp,
            )
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertEqual(json.loads(doctor.stdout)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
