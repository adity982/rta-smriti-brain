import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain.benchmark import default_public_benchmark_path, run_public_benchmark
from rta_brain.db import connect, graph_query, ingest_repo, init_project, remember, update_project_settings
from rta_brain.diagnostics import retrieval_diagnostics
from rta_brain.parsers import RegexParser


ROOT = Path(__file__).resolve().parents[1]


class ReleaseIntelligenceTests(unittest.TestCase):
    def test_retrieval_diagnostics_explain_provider_coverage_ranking_and_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "queue.md").write_text("Queue latency uses bounded backpressure and retry budgets.\n", encoding="utf-8")
            conn = connect(Path(tmp) / "brain.sqlite")
            try:
                init_project(conn, "demo", str(root))
                update_project_settings(conn, "demo", {"embedding_provider": "hash"}, root_path=str(root))
                ingest_repo(conn, root, project="demo")
                report = retrieval_diagnostics(conn, "latency backpressure", project="demo", limit=4)
            finally:
                conn.close()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["retrieval"]["mode"], "hybrid")
        self.assertEqual(report["index"]["embedding_coverage"], 1.0)
        self.assertEqual(report["freshness"]["state"], "fresh")
        self.assertGreaterEqual(report["latency_ms"], 0)
        self.assertEqual(report["results"][0]["path"], "queue.md")
        self.assertIn("hybrid_score", report["results"][0]["ranking"])
        self.assertTrue(report["results"][0]["evidence"]["source_hash"])
        self.assertEqual(report["query_terms"], ["backpressure", "latency"])
        reasons = report["results"][0]["selection_reasons"]
        self.assertIn("matched query terms: backpressure, latency", reasons)
        self.assertIn("hash-hybrid retrieval contributed semantic support", reasons)
        self.assertIn("fresh indexed snapshot with source hash", reasons)

    def test_parser_and_graph_queries_expose_calls_dependents_tests_and_impact(self):
        parsed = RegexParser().parse(Path("service.py"), "def run():\n    helper()\n")
        self.assertIn("helper", parsed.calls)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "service.py").write_text("def helper():\n    return 1\n\ndef run():\n    return helper()\n", encoding="utf-8")
            (root / "test_service.py").write_text("from service import helper\n\ndef test_helper():\n    assert helper() == 1\n", encoding="utf-8")
            conn = connect(Path(tmp) / "brain.sqlite")
            try:
                init_project(conn, "demo", str(root))
                ingest_repo(conn, root, project="demo")
                remember(conn, "helper behavior is relevant to release evidence", project="demo")
                dependents = graph_query(conn, project="demo", query_type="dependents", target="helper", depth=2)
                impact = graph_query(conn, project="demo", query_type="impact", target="helper", depth=2)
                evidence = graph_query(conn, project="demo", query_type="evidence", target="helper", depth=2)
                relevance = graph_query(conn, project="demo", query_type="relevance", target="release", depth=2)
            finally:
                conn.close()
        dependent_names = {node["name"] for node in dependents["nodes"]}
        relations = {edge["relation"] for edge in impact["edges"]}
        self.assertIn("test_service.py", dependent_names)
        self.assertTrue({"calls", "tests"} & relations)
        self.assertLessEqual(len(impact["nodes"]), 100)
        self.assertTrue(all(0 <= edge["confidence"] <= 1 for edge in impact["edges"]))
        self.assertEqual(set(evidence["relation_filter"]), {"contains", "mentions", "tests"})
        self.assertTrue({edge["relation"] for edge in evidence["edges"]} <= {"contains", "mentions", "tests"})
        self.assertTrue(
            all(edge["to_name"] == "helper" for edge in evidence["edges"] if edge["relation"] in {"contains", "tests"})
        )
        self.assertEqual(relevance["relation_filter"], ["mentions"])
        self.assertEqual({edge["relation"] for edge in relevance["edges"]}, {"mentions"})
        self.assertNotEqual(
            {edge["id"] for edge in impact["edges"]},
            {edge["id"] for edge in relevance["edges"]},
        )

    def test_public_benchmark_is_reproducible_private_safe_and_multimode(self):
        dataset = default_public_benchmark_path()
        self.assertEqual(dataset.read_bytes(), (ROOT / "benchmarks" / "public-v1.json").read_bytes())
        first = run_public_benchmark(dataset)
        second = run_public_benchmark(dataset)
        self.assertEqual(first["dataset_digest"], second["dataset_digest"])
        self.assertEqual(set(first["modes"]), {"no_memory", "lexical", "hash_hybrid", "optional_semantic"})
        self.assertEqual(first["modes"]["optional_semantic"]["status"], "not_requested")
        self.assertEqual(first["modes"]["no_memory"]["ndcg_at_k"], 0.0)
        self.assertGreater(first["modes"]["lexical"]["recall_at_k"], 0.0)
        self.assertGreater(first["modes"]["hash_hybrid"]["recall_at_k"], 0.0)
        self.assertEqual(first["quality_gates"]["stale_rejection"], 1.0)
        self.assertEqual(first["quality_gates"]["contradiction_detection"], 1.0)
        self.assertEqual(first["quality_gates"]["continuation_success"], 1.0)
        self.assertEqual(first["quality_gates"]["governance_accuracy"], 1.0)
        self.assertNotIn(str(Path.home()), str(first))
        self.assertNotIn("token", str(first).lower())

    def test_public_benchmark_reports_unavailable_optional_semantic_mode_without_failing(self):
        original = __import__("rta_brain.benchmark", fromlist=["_run_mode"])._run_mode

        def run_mode(payload, provider, model=None):
            if provider == "sentence-transformers":
                raise RuntimeError("synthetic unavailable model with private details")
            return original(payload, provider, model)

        with patch("rta_brain.benchmark._run_mode", side_effect=run_mode):
            result = run_public_benchmark(default_public_benchmark_path(), include_semantic=True)
        optional = result["modes"]["optional_semantic"]
        self.assertEqual(optional["status"], "unavailable")
        self.assertEqual(optional["provider"], "sentence-transformers")
        self.assertNotIn("private details", str(optional))

    def test_public_benchmark_rejects_oversized_or_unbounded_corpora(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "oversized.json"
            dataset.write_text(" " * 2_000_001, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "size limit"):
                run_public_benchmark(dataset)


if __name__ == "__main__":
    unittest.main()
