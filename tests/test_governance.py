import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rta_brain.db import connect, init_project
from rta_brain.governance import create_policy, list_policies, list_receipts, preflight, retire_policy
from rta_brain.mcp_server import RtaBrainMcpServer


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rta-brain.py"


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tempdir.name) / "brain.sqlite")
        init_project(self.conn, "demo", self.tempdir.name)

    def tearDown(self):
        self.conn.close()
        self.tempdir.cleanup()

    def test_verified_direct_policy_can_block_and_preserves_provenance(self):
        created = create_policy(
            self.conn,
            project="demo",
            kind="constraint",
            statement="Never deploy without an approved release receipt.",
            effect="block",
            action_contains="deploy",
            pramana="pratyaksha",
            confidence=0.98,
            provenance={
                "verification_status": "verified",
                "source_path": "docs/RELEASE_POLICY.md",
                "source_hash": "abc123",
            },
        )
        decision = preflight(self.conn, project="demo", action="Deploy production")
        self.assertEqual(decision["decision"], "block")
        self.assertEqual(decision["matches"][0]["policy_id"], created["policy"]["id"])
        self.assertEqual(decision["matches"][0]["provenance"]["source_path"], "docs/RELEASE_POLICY.md")

    def test_low_trust_block_is_demoted_to_warning(self):
        create_policy(
            self.conn,
            project="demo",
            kind="prohibited_repetition",
            statement="Do not rerun the old migration.",
            effect="block",
            action_contains="old migration",
            pramana="smriti",
            confidence=0.95,
            provenance={"verification_status": "unverified"},
        )
        decision = preflight(self.conn, project="demo", action="Rerun old migration")
        self.assertEqual(decision["decision"], "warn")
        self.assertEqual(decision["matches"][0]["requested_effect"], "block")
        self.assertEqual(decision["matches"][0]["effective_effect"], "warn")
        self.assertIn("insufficient trust", decision["matches"][0]["reason"])

    def test_required_check_blocks_only_when_verified_requirement_is_missing(self):
        create_policy(
            self.conn,
            project="demo",
            kind="required_check",
            statement="Run the release unit suite before committing.",
            effect="block",
            action_contains="commit",
            required_check="unit-suite",
            pramana="sabda",
            confidence=1.0,
            provenance={"verification_status": "verified", "source_path": "AGENTS.md", "source_hash": "policy-proof"},
        )
        missing = preflight(self.conn, project="demo", action="Commit release", completed_checks=[])
        satisfied = preflight(
            self.conn, project="demo", action="Commit release", completed_checks=["unit-suite"],
        )
        self.assertEqual(missing["decision"], "block")
        self.assertEqual(satisfied["decision"], "allow")
        self.assertEqual(satisfied["satisfied_policy_ids"], [missing["matches"][0]["policy_id"]])
        self.assertEqual(satisfied["completed_check_evidence"][0]["verification_status"], "owner_attested")
        self.assertTrue(satisfied["decision_receipt"]["action_digest"])
        self.assertTrue(satisfied["decision_receipt"]["policy_digest"])

    def test_path_scope_and_expiry_are_applied_deterministically(self):
        active = create_policy(
            self.conn,
            project="demo",
            kind="fragile_path",
            statement="Schema migrations require review.",
            effect="warn",
            path_glob="migrations/*.sql",
            pramana="sabda",
            confidence=0.9,
            provenance={"verification_status": "verified", "source_hash": "production-policy"},
        )["policy"]
        create_policy(
            self.conn,
            project="demo",
            kind="constraint",
            statement="Expired temporary freeze.",
            effect="block",
            action_contains="edit",
            expires_at="2000-01-01T00:00:00+00:00",
            pramana="pratyaksha",
            confidence=1.0,
            provenance={"verification_status": "verified", "source_hash": "privacy-policy"},
        )
        matched = preflight(
            self.conn, project="demo", action="Edit migration", path="migrations/001.sql",
        )
        unrelated = preflight(self.conn, project="demo", action="Edit docs", path="README.md")
        self.assertEqual(matched["decision"], "warn")
        self.assertEqual(matched["matches"][0]["policy_id"], active["id"])
        self.assertEqual(unrelated["decision"], "allow")

    def test_override_creates_an_immutable_audit_receipt(self):
        policy = create_policy(
            self.conn,
            project="demo",
            kind="constraint",
            statement="Production edits require explicit override.",
            effect="block",
            path_glob="src/prod/*",
            pramana="pratyaksha",
            confidence=1.0,
            provenance={"verification_status": "verified", "source_hash": "production-edit-policy"},
        )["policy"]
        decision = preflight(
            self.conn,
            project="demo",
            action="Edit production config",
            path="src/prod/settings.py",
            override_reason="Incident response approved by the operator.",
            actor="operator",
        )
        self.assertEqual(decision["initial_decision"], "block")
        self.assertEqual(decision["decision"], "allow_with_override")
        receipts = list_receipts(self.conn, project="demo")["receipts"]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["matched_policy_ids"], [policy["id"]])
        self.assertEqual(receipts[0]["override_reason"], "Incident response approved by the operator.")

    def test_policy_lifecycle_is_explicit(self):
        policy = create_policy(
            self.conn,
            project="demo",
            kind="failed_approach",
            statement="The legacy parser corrupts multiline strings.",
            action_contains="legacy parser",
            pramana="pratyaksha",
            confidence=0.9,
            provenance={"verification_status": "verified"},
        )["policy"]
        retire_policy(self.conn, project="demo", policy_id=policy["id"], reason="Parser replaced")
        policies = list_policies(self.conn, project="demo", include_retired=True)["policies"]
        self.assertEqual(policies[0]["status"], "retired")
        self.assertEqual(policies[0]["retired_reason"], "Parser replaced")
        self.assertEqual(preflight(self.conn, project="demo", action="Use legacy parser")["decision"], "allow")

    def test_mcp_exposes_read_only_policy_preflight_without_agent_override(self):
        create_policy(
            self.conn,
            project="demo",
            kind="constraint",
            statement="Do not publish without privacy proof.",
            effect="block",
            action_contains="publish",
            pramana="pratyaksha",
            confidence=1.0,
            provenance={"verification_status": "verified", "source_hash": "mcp-privacy-policy"},
        )
        server = RtaBrainMcpServer(Path(self.tempdir.name) / "brain.sqlite", "demo")
        tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertNotIn("brain_policy_add", names)
        self.assertNotIn("brain_policy_retire", names)
        checked = server.call_tool("brain_preflight", {
            "action": "Publish release",
        })["structuredContent"]
        self.assertEqual(checked["decision"], "block")
        with self.assertRaisesRegex(ValueError, "owner-controlled"):
            server.call_tool("brain_preflight", {
                "action": "Publish release",
                "override_reason": "Agent supplied owner approval.",
            })
        receipts = server.call_tool("brain_governance_receipts", {})["structuredContent"]
        self.assertEqual(receipts["receipts"], [])

    def test_preflight_rejects_unstructured_checks_and_unsafe_paths(self):
        with self.assertRaisesRegex(ValueError, "completed_checks must be a list"):
            preflight(self.conn, project="demo", action="Commit", completed_checks="unit-suite")
        for unsafe in ("../outside.py", "C:\\repo\\file.py", "/tmp/file.py", "//server/share/file.py"):
            with self.subTest(path=unsafe):
                with self.assertRaisesRegex(ValueError, "project-relative"):
                    preflight(self.conn, project="demo", action="Edit", path=unsafe)

    def test_operational_context_warns_before_consequential_actions(self):
        decision = preflight(
            self.conn,
            project="demo",
            action="Publish the next release",
            path="docs/RELEASE.md",
            operational_context={
                "readiness": {
                    "operational_state": "operationally_not_ready",
                    "reasons": ["no_structured_checkpoint"],
                },
                "git": {
                    "repository_root": self.tempdir.name,
                    "branch": "main",
                    "head": "abc123",
                    "dirty_files": 2,
                },
                "freshness": {
                    "state": "stale",
                    "changed": 1,
                    "missing": 0,
                    "added": 0,
                    "uninspectable": 0,
                },
            },
        )
        kinds = {item["kind"] for item in decision["matches"]}
        self.assertEqual(decision["decision"], "warn")
        self.assertIn("operational_readiness", kinds)
        self.assertIn("dirty_worktree", kinds)
        self.assertIn("stale_index", kinds)
        self.assertTrue(any("no_structured_checkpoint" in item["reason"] for item in decision["matches"]))
        self.assertTrue(decision["operational_context"]["consequential_action"])
        self.assertTrue(decision["decision_receipt"]["operational_digest"])

    def test_cli_block_decision_uses_a_nonzero_exit_code(self):
        db_path = Path(self.tempdir.name) / "brain.sqlite"
        add = subprocess.run(
            [
                sys.executable, str(CLI), "--db", str(db_path), "--json", "policy", "add",
                "--project", "demo", "--kind", "constraint", "--statement", "Do not delete evidence.",
                "--effect", "block", "--action-contains", "delete evidence",
                "--pramana", "pratyaksha", "--confidence", "1",
                "--verification-status", "verified",
                "--source-hash", "cli-policy-proof",
            ],
            text=True, capture_output=True, cwd=ROOT,
        )
        self.assertEqual(add.returncode, 0, add.stderr)
        blocked = subprocess.run(
            [
                sys.executable, str(CLI), "--db", str(db_path), "--json", "preflight",
                "Delete evidence now", "--project", "demo",
            ],
            text=True, capture_output=True, cwd=ROOT,
        )
        self.assertEqual(blocked.returncode, 2, blocked.stderr)
        self.assertEqual(json.loads(blocked.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
