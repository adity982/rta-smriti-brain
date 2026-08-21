import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rta-brain.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class TemporalTruthCliTests(unittest.TestCase):
    def test_assert_and_read_current_truth_as_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            database = Path(tmp) / "brain.sqlite"
            initialized = run_cli(
                "--db", str(database), "--json", "init",
                "--project", "demo", "--root", str(root),
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)

            asserted = run_cli(
                "--db", str(database), "--json", "truth", "assert",
                "--project", "demo", "--root", str(root),
                "--claim-id", "release-status",
                "--subject", "release:v0.7", "--predicate", "status",
                "--value-json", '"candidate"',
                "--idempotency-key", "cli:release-status:1",
                "--expected-version", "0",
            )
            self.assertEqual(asserted.returncode, 0, asserted.stderr)
            assertion = json.loads(asserted.stdout)
            self.assertEqual(assertion["event"]["stream_version"], 1)

            current = run_cli(
                "--db", str(database), "--json", "truth", "current",
                "--project", "demo", "--claim-id", "release-status",
            )
            self.assertEqual(current.returncode, 0, current.stderr)
            payload = json.loads(current.stdout)
            self.assertEqual(payload["claim"]["object"], "candidate")
            self.assertEqual(payload["claim"]["effective_state"], "observed")

            accepted = run_cli(
                "--db", str(database), "--json", "truth", "state",
                "--project", "demo", "--root", str(root),
                "--claim-id", "release-status", "--state", "accepted",
                "--reason", "Owner reviewed the evidence.",
                "--idempotency-key", "cli:release-status:state:2",
                "--expected-version", "1", "--actor-id", "owner",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            history = run_cli(
                "--db", str(database), "--json", "truth", "history",
                "--project", "demo", "--claim-id", "release-status",
            )
            self.assertEqual(history.returncode, 0, history.stderr)
            versions = json.loads(history.stdout)["versions"]
            self.assertEqual(
                [version["epistemic_state"] for version in versions],
                ["observed", "accepted"],
            )

            as_of = run_cli(
                "--db", str(database), "--json", "truth", "as-of",
                "--project", "demo", "--claim-id", "release-status",
                "--valid-at", "2026-08-22T00:00:00+00:00",
                "--recorded-sequence", "1",
            )
            self.assertEqual(as_of.returncode, 0, as_of.stderr)
            self.assertEqual(json.loads(as_of.stdout)["claim"]["epistemic_state"], "observed")

    def test_complete_temporal_operator_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "proof.txt").write_text("verified\n", encoding="utf-8")
            database = Path(tmp) / "brain.sqlite"
            self.assertEqual(run_cli(
                "--db", str(database), "--json", "init",
                "--project", "demo", "--root", str(root),
            ).returncode, 0)

            def truth(*args):
                result = run_cli(
                    "--db", str(database), "--json", "truth", *args
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            truth(
                "assert", "--project", "demo", "--root", str(root),
                "--claim-id", "release-status", "--subject", "release:v0.7",
                "--predicate", "status", "--value-json", '"candidate"',
                "--idempotency-key", "cli:assert:release", "--expected-version", "0",
            )
            revised = truth(
                "revise", "--project", "demo", "--root", str(root),
                "--claim-id", "release-status", "--value-json", '"qualified"',
                "--reason", "Focused verification passed.",
                "--idempotency-key", "cli:revise:release", "--expected-version", "1",
            )
            self.assertEqual(revised["claim"]["object"], "qualified")
            truth(
                "assert", "--project", "demo", "--root", str(root),
                "--claim-id", "release-blocked", "--subject", "release:v0.7",
                "--predicate", "status", "--value-json", '"blocked"',
                "--idempotency-key", "cli:assert:blocked", "--expected-version", "0",
            )
            truth(
                "relate", "--project", "demo", "--root", str(root),
                "--relation-id", "status-conflict", "--from-claim", "release-status",
                "--type", "contradicts", "--to-claim", "release-blocked",
                "--idempotency-key", "cli:relate:status", "--expected-version", "0",
            )
            truth(
                "evidence", "--project", "demo", "--root", str(root),
                "--claim-id", "release-status", "--evidence-id", "proof-file",
                "--source-identifier", "proof.txt", "--method", "file observation",
                "--polarity", "supporting", "--authority-class", "operator",
                "--confidence", "0.9", "--provenance-json", '{"path":"proof.txt"}',
                "--idempotency-key", "cli:evidence:proof", "--expected-version", "0",
            )
            explained = truth(
                "explain", "--project", "demo", "--claim-id", "release-status",
            )
            self.assertEqual(explained["claim"]["effective_state"], "disputed")
            self.assertEqual(explained["evidence"][0]["evidence_id"], "proof-file")

            abstained = truth(
                "abstain", "--project", "demo", "--root", str(root),
                "--abstention-id", "missing-platform-proof",
                "--query-scope", "macOS release readiness",
                "--missing-evidence-json", '["macOS clean install"]',
                "--unresolved-conflicts-json", "[]",
                "--minimum-revalidation-action", "Run the macOS operator suite.",
                "--idempotency-key", "cli:abstain:macos", "--expected-version", "0",
            )
            self.assertEqual(abstained["status"], "abstain")

            truth(
                "validator", "add", "--project", "demo", "--root", str(root),
                "--validator-id", "proof-exists", "--type", "file_exists",
                "--claim-id", "release-status", "--config-json", '{"path":"proof.txt"}',
                "--failure-effect", "stale", "--idempotency-key", "cli:validator:add",
                "--expected-version", "0",
            )
            evaluated = truth(
                "validator", "run", "--project", "demo", "--root", str(root),
                "--validator-id", "proof-exists", "--idempotency-key", "cli:validator:run",
                "--expected-version", "1",
            )
            self.assertEqual(evaluated["evaluation"]["outcome"], "pass")
            validator_history = truth(
                "validator", "history", "--project", "demo",
                "--validator-id", "proof-exists",
            )
            self.assertEqual(len(validator_history["results"]), 1)

            diff = truth(
                "diff", "--project", "demo", "--from-sequence", "1",
                "--to-sequence", "2", "--valid-at", "2099-01-01T00:00:00+00:00",
            )
            self.assertEqual(diff["changes"][0]["claim_id"], "release-status")
            verified = truth("ledger", "verify", "--project", "demo")
            self.assertTrue(verified["chain_valid"])
            rebuilt = truth(
                "projection", "rebuild", "--project", "demo", "--root", str(root),
            )
            self.assertGreaterEqual(rebuilt["events_replayed"], 8)
            compared = truth("projection", "compare", "--project", "demo")
            self.assertTrue(compared["last_rebuilt_digest_matches"])


if __name__ == "__main__":
    unittest.main()
