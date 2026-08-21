import tempfile
import unittest
from pathlib import Path

from rta_brain import db
from rta_brain.context import build_context_pack
from rta_brain.continuity import operational_readiness
from rta_brain.diagnostics import retrieval_diagnostics
from rta_brain.temporal import (
    append_claim,
    define_validator,
    relate_claims,
    run_validator,
    truth_overview,
)


class TemporalTruthIntegrationTests(unittest.TestCase):
    def test_disputed_truth_and_failed_validator_propagate_to_search_pack_and_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.init_project(conn, "demo", str(root))
                db.save_checkpoint(conn, "demo", "Qualify release truth")
                append_claim(
                    conn, project="demo", active_root=root, claim_id="ready",
                    subject="release:v0.7", predicate="status", value="ready",
                    epistemic_state="accepted", actor_type="operator",
                    idempotency_key="ready:1", expected_stream_version=0,
                )
                append_claim(
                    conn, project="demo", active_root=root, claim_id="blocked",
                    subject="release:v0.7", predicate="status", value="blocked",
                    idempotency_key="blocked:1", expected_stream_version=0,
                )
                relate_claims(
                    conn, project="demo", active_root=root,
                    relation_id="release-conflict", from_claim_id="ready",
                    relation_type="contradicts", to_claim_id="blocked",
                    idempotency_key="relation:1", expected_stream_version=0,
                )
                define_validator(
                    conn, project="demo", active_root=root,
                    validator_id="release-proof", validator_type="file_exists",
                    claim_id="ready", config={"path": "missing-proof.txt"},
                    failure_effect="stale", idempotency_key="validator:1",
                    expected_stream_version=0,
                )
                run_validator(
                    conn, project="demo", active_root=root,
                    validator_id="release-proof", idempotency_key="validator:2",
                    expected_stream_version=1,
                )

                searched = db.search(conn, "release status", project="demo")
                self.assertEqual(searched["truth"][0]["claim_id"], "ready")
                self.assertEqual(searched["truth"][0]["effective_state"], "stale")
                self.assertEqual(searched["truth"][0]["contradictions"], ["blocked"])
                diagnostics = retrieval_diagnostics(
                    conn, "release status", project="demo"
                )
                self.assertEqual(
                    diagnostics["truth_results"][0]["claim_id"], "ready"
                )
                self.assertIn(
                    "contradicted",
                    " ".join(diagnostics["truth_results"][0]["selection_reasons"]),
                )

                pack = build_context_pack(
                    conn, "release status", project="demo", max_tokens=2000
                )
                self.assertIn("## Temporal Truth", pack)
                self.assertIn("DISPUTED", pack)
                self.assertIn("release:v0.7", pack)

                readiness = operational_readiness(conn, "demo")
                self.assertFalse(readiness["continuation_ready"])
                self.assertIn("truth_contradictions", readiness["reasons"])
                self.assertIn("truth_validator_failures", readiness["reasons"])
                self.assertTrue(readiness["temporal_truth"]["ledger_intact"])
                health = db.doctor(conn)
                self.assertEqual(health["temporal"]["truth_events"], 5)
                self.assertTrue(health["temporal"]["all_ledgers_intact"])
                overview = truth_overview(conn, project="demo")
                self.assertEqual(overview["counts"]["current_claims"], 2)
                self.assertEqual(overview["counts"]["contradictions"], 1)
                self.assertEqual(overview["counts"]["failed_validators"], 1)
                self.assertEqual(overview["events"][0]["event_type"], "validator_evaluated.v1")
            finally:
                conn.close()

    def test_event_tampering_fails_operational_readiness_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.init_project(conn, "demo", str(root))
                db.save_checkpoint(conn, "demo", "Continue safely")
                append_claim(
                    conn, project="demo", active_root=root, claim_id="claim-1",
                    subject="ledger", predicate="integrity", value="intact",
                    idempotency_key="claim:1", expected_stream_version=0,
                )
                conn.execute("DROP TRIGGER truth_events_no_update")
                conn.execute(
                    "UPDATE truth_events SET payload_json = '{\"tampered\":true}'"
                )
                conn.commit()

                readiness = operational_readiness(conn, "demo")
                self.assertFalse(readiness["continuation_ready"])
                self.assertIn("truth_ledger_integrity", readiness["reasons"])
                self.assertFalse(readiness["temporal_truth"]["ledger_intact"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
