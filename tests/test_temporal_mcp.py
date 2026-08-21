import tempfile
import unittest
from pathlib import Path

from rta_brain.db import connect, init_project
from rta_brain.mcp_server import RtaBrainMcpServer
from rta_brain.temporal import append_claim


class TemporalTruthMcpTests(unittest.TestCase):
    def _brain(self, directory: str):
        root = Path(directory) / "repo"
        root.mkdir()
        database = Path(directory) / "brain.sqlite"
        conn = connect(database)
        init_project(conn, "demo", str(root))
        return conn, database, root

    def test_temporal_reads_are_default_but_writes_are_capability_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, database, root = self._brain(tmp)
            try:
                append_claim(
                    conn,
                    project="demo",
                    active_root=root,
                    claim_id="claim-1",
                    subject="release",
                    predicate="status",
                    value={"phase": "candidate"},
                    idempotency_key="assert-claim-1",
                    expected_stream_version=0,
                )
            finally:
                conn.close()

            server = RtaBrainMcpServer(database, "demo")
            exposed = {tool["name"] for tool in server.agent_tools}
            self.assertTrue(
                {
                    "brain_truth_current",
                    "brain_truth_as_of",
                    "brain_truth_history",
                    "brain_truth_diff",
                    "brain_truth_explain",
                }.issubset(exposed)
            )
            self.assertNotIn("brain_truth_assert", exposed)
            self.assertNotIn("brain_truth_validator_run", exposed)

            result = server.call_tool(
                "brain_truth_current", {"claim_id": "claim-1"}
            )["structuredContent"]
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["claim"]["object"], {"phase": "candidate"})

    def test_default_agent_reads_redact_sensitive_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, database, root = self._brain(tmp)
            try:
                append_claim(
                    conn, project="demo", active_root=root, claim_id="private-claim",
                    subject="credential:service", predicate="token",
                    value="must-not-reach-agent-context", privacy_class="restricted",
                    idempotency_key="private:1", expected_stream_version=0,
                )
            finally:
                conn.close()
            server = RtaBrainMcpServer(database, "demo")
            for tool, arguments in (
                ("brain_truth_current", {"claim_id": "private-claim"}),
                ("brain_truth_history", {"claim_id": "private-claim"}),
                ("brain_truth_explain", {"claim_id": "private-claim"}),
            ):
                result = server.call_tool(tool, arguments)["structuredContent"]
                serialized = str(result)
                self.assertNotIn("must-not-reach-agent-context", serialized)
                self.assertNotIn("credential:service", serialized)
                self.assertIn("redacted", serialized)

    def test_truth_writes_are_agent_scoped_and_cannot_self_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, database, root = self._brain(tmp)
            conn.close()
            denied = RtaBrainMcpServer(database, "demo")
            with self.assertRaisesRegex(ValueError, "not enabled"):
                denied.call_tool(
                    "brain_truth_assert",
                    {
                        "claim_id": "agent-claim",
                        "subject": "build",
                        "predicate": "status",
                        "value": "green",
                        "idempotency_key": "agent-assert",
                        "expected_version": 0,
                    },
                )

            server = RtaBrainMcpServer(database, "demo", allow_truth_writes=True)
            exposed = {tool["name"] for tool in server.agent_tools}
            self.assertIn("brain_truth_assert", exposed)
            self.assertNotIn("brain_truth_validator_run", exposed)
            schema = next(
                tool for tool in server.agent_tools
                if tool["name"] == "brain_truth_assert"
            )["inputSchema"]["properties"]
            self.assertNotIn("actor_type", schema)
            self.assertEqual(schema["epistemic_state"]["enum"], ["hypothesis", "observed"])

            created = server.call_tool(
                "brain_truth_assert",
                {
                    "claim_id": "agent-claim",
                    "subject": "build",
                    "predicate": "status",
                    "value": "green",
                    "idempotency_key": "agent-assert",
                    "expected_version": 0,
                    "epistemic_state": "observed",
                },
            )["structuredContent"]
            self.assertEqual(created["claim"]["epistemic_state"], "observed")

            with self.assertRaisesRegex(ValueError, "accepted"):
                server.call_tool(
                    "brain_truth_state",
                    {
                        "claim_id": "agent-claim",
                        "state": "accepted",
                        "reason": "agent says so",
                        "idempotency_key": "agent-accept",
                        "expected_version": 1,
                    },
                )

            owner = connect(database)
            try:
                append_claim(
                    owner, project="demo", active_root=root, claim_id="owner-approved",
                    subject="release", predicate="status", value="approved",
                    epistemic_state="accepted", idempotency_key="owner:accepted:1",
                    expected_stream_version=0,
                )
            finally:
                owner.close()
            with self.assertRaisesRegex(PermissionError, "operator-authoritative"):
                server.call_tool(
                    "brain_truth_revise",
                    {
                        "claim_id": "owner-approved", "value": "replaced",
                        "reason": "agent rewrite", "idempotency_key": "owner:rewrite:2",
                        "expected_version": 1,
                    },
                )

    def test_validator_execution_requires_its_own_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, database, root = self._brain(tmp)
            conn.close()
            write_server = RtaBrainMcpServer(
                database, "demo", allow_truth_writes=True
            )
            self.assertNotIn(
                "brain_truth_validator_run",
                {tool["name"] for tool in write_server.agent_tools},
            )
            validator_server = RtaBrainMcpServer(
                database,
                "demo",
                allow_truth_writes=True,
                allow_validator_run=True,
            )
            self.assertIn(
                "brain_truth_validator_run",
                {tool["name"] for tool in validator_server.agent_tools},
            )

    def test_temporal_write_capability_covers_agent_evidence_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, database, root = self._brain(tmp)
            conn.close()
            (root / "proof.txt").write_text("proof\n", encoding="utf-8")
            server = RtaBrainMcpServer(
                database,
                "demo",
                allow_truth_writes=True,
                allow_validator_run=True,
            )
            exposed = {tool["name"] for tool in server.agent_tools}
            self.assertTrue({
                "brain_truth_revise",
                "brain_truth_relate",
                "brain_truth_evidence",
                "brain_truth_abstain",
                "brain_truth_validator_define",
            }.issubset(exposed))

            def call(name, **arguments):
                return server.call_tool(name, arguments)["structuredContent"]

            call(
                "brain_truth_assert", claim_id="claim-a", subject="release",
                predicate="status", value="candidate", idempotency_key="a:1",
                expected_version=0,
            )
            call(
                "brain_truth_assert", claim_id="claim-b", subject="release",
                predicate="status", value="blocked", idempotency_key="b:1",
                expected_version=0,
            )
            revised = call(
                "brain_truth_revise", claim_id="claim-a", value="qualified",
                reason="agent observed focused tests", idempotency_key="a:2",
                expected_version=1,
            )
            self.assertEqual(revised["claim"]["object"], "qualified")
            call(
                "brain_truth_relate", relation_id="relation-1",
                from_claim_id="claim-a", relation_type="contradicts",
                to_claim_id="claim-b", idempotency_key="relation:1",
                expected_version=0,
            )
            call(
                "brain_truth_evidence", claim_id="claim-a", evidence_id="evidence-1",
                source_identifier="proof.txt", method="agent file observation",
                polarity="supporting", confidence=0.7,
                provenance={"path": "proof.txt"}, idempotency_key="evidence:1",
                expected_version=0,
            )
            abstention = call(
                "brain_truth_abstain", abstention_id="abstention-1",
                query_scope="macOS readiness", missing_evidence=["macOS run"],
                unresolved_conflicts=[], minimum_revalidation_action="Run macOS tests",
                idempotency_key="abstention:1", expected_version=0,
            )
            self.assertEqual(abstention["status"], "abstain")
            call(
                "brain_truth_validator_define", validator_id="proof-exists",
                validator_type="file_exists", claim_id="claim-a",
                config={"path": "proof.txt"}, failure_effect="stale",
                idempotency_key="validator:define", expected_version=0,
            )
            evaluation = call(
                "brain_truth_validator_run", validator_id="proof-exists",
                idempotency_key="validator:run", expected_version=1,
            )
            self.assertEqual(evaluation["evaluation"]["outcome"], "pass")


if __name__ == "__main__":
    unittest.main()
