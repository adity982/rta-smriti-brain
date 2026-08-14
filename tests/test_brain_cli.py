import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rta-brain.py"


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
    )


class RtaBrainCliTests(unittest.TestCase):
    def test_init_remember_search_and_doctor_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"

            init = run_cli("--db", str(db), "--json", "init", "--project", "demo", "--root", tmp)
            self.assertEqual(init.returncode, 0, init.stderr)
            init_payload = json.loads(init.stdout)
            self.assertEqual(init_payload["status"], "ok")
            self.assertTrue(db.exists())

            remember = run_cli(
                "--db",
                str(db),
                "--json",
                "remember",
                "Use fail-closed attestation before release.",
                "--type",
                "decision",
                "--pramana",
                "sabda",
                "--project",
                "demo",
                "--confidence",
                "0.92",
                "--priority",
                "8",
            )
            self.assertEqual(remember.returncode, 0, remember.stderr)
            remembered = json.loads(remember.stdout)
            self.assertEqual(remembered["memory"]["pramana"], "sabda")

            search = run_cli("--db", str(db), "--json", "search", "attestation release")
            self.assertEqual(search.returncode, 0, search.stderr)
            results = json.loads(search.stdout)
            self.assertEqual(results["status"], "ok")
            self.assertGreaterEqual(len(results["memories"]), 1)
            self.assertIn("fail-closed", results["memories"][0]["text"])

            doctor = run_cli("--db", str(db), "--json", "doctor")
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            health = json.loads(doctor.stdout)
            self.assertEqual(health["status"], "ok")
            self.assertTrue(health["fts_enabled"])

    def test_ingest_repo_indexes_files_symbols_imports_and_ignores_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / ".git").mkdir()
            (root / ".git" / "ignored.py").write_text("def hidden(): pass", encoding="utf-8")
            (root / "tmp_debug").mkdir()
            (root / "tmp_debug" / "noise.py").write_text("def noisy_tmp_symbol(): pass", encoding="utf-8")
            (root / ".venv-wsl-cuda").mkdir()
            (root / ".venv-wsl-cuda" / "venv_noise.py").write_text("def noisy_venv_symbol(): pass", encoding="utf-8")
            (root / "output").mkdir()
            (root / "output" / "generated.md").write_text("# Generated output\n", encoding="utf-8")
            (root / "app.py").write_text(
                "import json\n\nclass Engine:\n    pass\n\ndef run_engine():\n    return json.dumps({'ok': True})\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("# Demo\nRta-Smriti local brain.\n", encoding="utf-8")
            db = Path(tmp) / "brain.sqlite"

            result = run_cli("--db", str(db), "--json", "ingest-repo", str(root), "--project", "demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["indexed_files"], 2)
            self.assertGreaterEqual(payload["symbols"], 2)
            self.assertGreaterEqual(payload["edges"], 2)

            graph = run_cli("--db", str(db), "--json", "graph", "--project", "demo")
            self.assertEqual(graph.returncode, 0, graph.stderr)
            graph_payload = json.loads(graph.stdout)
            names = {node["name"] for node in graph_payload["nodes"]}
            self.assertIn("Engine", names)
            self.assertIn("run_engine", names)
            self.assertNotIn("hidden", names)
            self.assertNotIn("noisy_tmp_symbol", names)
            self.assertNotIn("noisy_venv_symbol", names)

    def test_context_pack_includes_memories_files_pramana_and_stale_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            target = root / "core.py"
            target.write_text("def attestation_gate():\n    return 'closed'\n", encoding="utf-8")
            db = Path(tmp) / "brain.sqlite"

            self.assertEqual(run_cli("--db", str(db), "ingest-repo", str(root), "--project", "demo").returncode, 0)
            self.assertEqual(
                run_cli(
                    "--db",
                    str(db),
                    "remember",
                    "The attestation gate must fail closed when proof is missing.",
                    "--type",
                    "constraint",
                    "--pramana",
                    "sabda",
                    "--project",
                    "demo",
                    "--priority",
                    "9",
                ).returncode,
                0,
            )

            pack = run_cli("--db", str(db), "context-pack", "change attestation gate", "--project", "demo")
            self.assertEqual(pack.returncode, 0, pack.stderr)
            self.assertIn("# Rta-Smriti Context Pack", pack.stdout)
            self.assertIn("Pramana: sabda", pack.stdout)
            self.assertIn("core.py", pack.stdout)
            self.assertIn("stale status: fresh", pack.stdout)

            target.write_text("def attestation_gate():\n    return 'open'\n", encoding="utf-8")
            stale = run_cli("--db", str(db), "--json", "stale-check", "--project", "demo")
            self.assertEqual(stale.returncode, 0, stale.stderr)
            stale_payload = json.loads(stale.stdout)
            self.assertEqual(stale_payload["changed"], 1)
            self.assertEqual(stale_payload["missing"], 0)


if __name__ == "__main__":
    unittest.main()
