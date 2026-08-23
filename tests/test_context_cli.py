import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rta_brain.context_host import build_task_contract

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rta-brain.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class ContextCliTests(unittest.TestCase):
    def _run(self, database, *args):
        result = run_cli("--db", str(database), "--json", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_operator_authorizes_and_agent_compiles_without_bearer_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Fixture"],
                check=True,
            )
            (root / "README.md").write_text("verified context\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "fixture"],
                check=True,
                capture_output=True,
            )
            database = Path(tmp) / "brain.sqlite"
            self._run(database, "init", "--project", "demo", "--root", str(root))
            profile = self._run(
                database,
                "context",
                "profile-register",
                "--project",
                "demo",
                "--profile-id",
                "codex",
                "--operator-id",
                "owner",
                "--max-input-tokens",
                "8192",
            )
            contract = build_task_contract(
                project="demo",
                agent_profile_id="codex",
                objective="Resume the verified task.",
                actor_id="owner",
                comparison_modes=["minimal"],
            )
            contract_path = Path(tmp) / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            authorized = self._run(
                database,
                "context",
                "contract-authorize",
                "--project",
                "demo",
                "--profile-version-id",
                str(profile["agent_profile_version_id"]),
                "--contract-file",
                str(contract_path),
                "--operator-id",
                "owner",
            )
            compiled = self._run(
                database,
                "context",
                "compile",
                "--project",
                "demo",
                "--root",
                str(root),
                "--task-contract-id",
                str(authorized["task_contract_id"]),
                "--principal-id",
                "codex",
                "--session-id",
                "task-1",
            )
            compilation_id = compiled["compilation_receipt"]["compilation_id"]
            explained = self._run(
                database,
                "context",
                "explain",
                "--project",
                "demo",
                "--compilation-id",
                compilation_id,
                "--principal-id",
                "codex",
                "--session-id",
                "task-1",
            )
            audited = self._run(
                database,
                "context",
                "audit",
                "--project",
                "demo",
                "--compilation-id",
                compilation_id,
                "--operator-id",
                "owner",
                "--session-id",
                "operator-task",
            )
            outcome_path = Path(tmp) / "outcome.json"
            outcome_path.write_text(
                json.dumps(
                    {
                        "outcome_id": "cli-outcome-1",
                        "task_status": "success",
                        "evidence": {"operator_review": "passed"},
                        "acceptance_results": {"context": "accepted"},
                        "attributions": [],
                    }
                ),
                encoding="utf-8",
            )
            outcome = self._run(
                database,
                "context",
                "outcome",
                "--project",
                "demo",
                "--compilation-id",
                compilation_id,
                "--outcome-file",
                str(outcome_path),
                "--operator-id",
                "owner",
                "--session-id",
                "operator-task",
            )
            revoked = self._run(
                database,
                "context",
                "revoke",
                "--project",
                "demo",
                "--compilation-id",
                compilation_id,
                "--operator-id",
                "owner",
                "--reason",
                "CLI acceptance test complete.",
            )

        serialized = json.dumps(
            {
                "compiled": compiled,
                "explained": explained,
                "audited": audited,
                "outcome": outcome,
                "revoked": revoked,
            },
            sort_keys=True,
        )
        self.assertEqual(compiled["status"], "stable")
        self.assertTrue(explained["receipt_integrity_verified"])
        self.assertTrue(audited["receipt_integrity_verified"])
        self.assertEqual(revoked["status"], "revoked")
        self.assertNotIn("grant_id", revoked)
        self.assertNotIn("capability_token", serialized)
        self.assertNotIn("authority_secret", serialized)


if __name__ == "__main__":
    unittest.main()
