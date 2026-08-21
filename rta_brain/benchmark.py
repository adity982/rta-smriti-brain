"""Reproducible public benchmark runner over a synthetic corpus."""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import tempfile
from pathlib import Path, PurePosixPath
from statistics import median
from time import perf_counter

from .context import build_continuation_prompt
from .db import (
    connect, ingest_repo, init_project, reflect, remember, save_checkpoint, search,
    stale_check, update_project_settings,
)
from .governance import create_policy, preflight


MAX_PUBLIC_BENCHMARK_BYTES = 2_000_000
MAX_PUBLIC_DOCUMENTS = 5_000
MAX_PUBLIC_QUERIES = 1_000


def default_public_benchmark_path() -> Path:
    """Return the benchmark corpus shipped inside installed distributions."""
    return Path(__file__).with_name("data") / "public-v1.json"


def _load_dataset(path: Path) -> tuple[dict, str]:
    dataset = Path(path)
    if not dataset.is_file():
        raise ValueError(f"benchmark dataset does not exist: {dataset}")
    if dataset.stat().st_size > MAX_PUBLIC_BENCHMARK_BYTES:
        raise ValueError(f"benchmark dataset exceeds the {MAX_PUBLIC_BENCHMARK_BYTES:,} byte size limit")
    raw = dataset.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("benchmark dataset is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("benchmark dataset must be an object")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported benchmark schema version")
    documents = payload.get("documents")
    queries = payload.get("queries")
    if (
        not isinstance(documents, list) or not documents or len(documents) > MAX_PUBLIC_DOCUMENTS
        or not isinstance(queries, list) or not queries or len(queries) > MAX_PUBLIC_QUERIES
    ):
        raise ValueError("benchmark requires non-empty documents and queries")
    known_paths = set()
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("benchmark documents must be objects")
        relative = str(item.get("path") or "").replace("\\", "/")
        if (
            not relative or len(relative) > 1_000 or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts or relative in known_paths
        ):
            raise ValueError("benchmark document paths must be relative")
        if not isinstance(item.get("text"), str) or len(item["text"]) > 1_000_000:
            raise ValueError("benchmark document text must be a bounded string")
        known_paths.add(relative)
    for item in queries:
        if not isinstance(item, dict):
            raise ValueError("benchmark queries must be objects")
        if (
            not isinstance(item.get("query"), str) or not item["query"].strip()
            or len(item["query"]) > 2_000
        ):
            raise ValueError("benchmark query must be a non-empty string")
        relevant = item.get("relevant_paths")
        if (
            not isinstance(relevant, list) or not relevant or len(relevant) > 100
            or any(not isinstance(value, str) for value in relevant) or not set(relevant) <= known_paths
        ):
            raise ValueError("benchmark relevant paths must reference corpus documents")
    return payload, hashlib.sha256(raw).hexdigest()


def _rank_metrics(retrieved: list[str], relevant: set[str], k: int) -> tuple[float, float, float, float]:
    selected = retrieved[:k]
    gains = [1.0 if path in relevant else 0.0 for path in selected]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    hits = sum(gains)
    first = next((index + 1 for index, path in enumerate(selected) if path in relevant), None)
    return (
        dcg / ideal if ideal else 0.0,
        hits / len(relevant),
        (1.0 / first) if first else 0.0,
        hits / len(selected) if selected else 0.0,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def _run_mode(payload: dict, provider: str, model: str | None = None) -> dict:
    if provider == "no_memory":
        return {
            "ndcg_at_k": 0.0, "recall_at_k": 0.0, "mrr_at_k": 0.0,
            "precision_at_k": 0.0, "context_efficiency": 0.0,
            "latency_ms": {"p50": 0.0, "p95": 0.0},
        }
    with tempfile.TemporaryDirectory(prefix="rta-public-bench-") as tmp:
        root = Path(tmp) / "corpus"
        root.mkdir()
        for document in payload["documents"]:
            destination = root / PurePosixPath(document["path"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(document["text"], encoding="utf-8")
        conn = connect(Path(tmp) / "brain.sqlite")
        try:
            init_project(conn, "benchmark", str(root))
            if provider in {"hash_hybrid", "sentence-transformers"}:
                settings = {
                    "embedding_provider": "hash" if provider == "hash_hybrid" else "sentence-transformers",
                }
                if model:
                    settings["embedding_model"] = model
                update_project_settings(conn, "benchmark", settings, root_path=str(root))
            ingest_repo(conn, root, project="benchmark")
            scores = []
            latencies = []
            returned = 0
            relevant_returned = 0
            k = min(5, len(payload["documents"]))
            for query in payload["queries"]:
                started = perf_counter()
                result = search(conn, query["query"], project="benchmark", limit=k)
                latencies.append((perf_counter() - started) * 1000)
                paths = [str(item["path"]) for item in result["chunks"]]
                relevant = set(query["relevant_paths"])
                metric = _rank_metrics(paths, relevant, k)
                scores.append(metric)
                returned += len(paths)
                relevant_returned += sum(path in relevant for path in paths)
        finally:
            conn.close()
    count = len(scores)
    return {
        "ndcg_at_k": round(sum(item[0] for item in scores) / count, 6),
        "recall_at_k": round(sum(item[1] for item in scores) / count, 6),
        "mrr_at_k": round(sum(item[2] for item in scores) / count, 6),
        "precision_at_k": round(sum(item[3] for item in scores) / count, 6),
        "context_efficiency": round(relevant_returned / returned, 6) if returned else 0.0,
        "latency_ms": {"p50": round(median(latencies), 3), "p95": round(_percentile(latencies, 0.95), 3)},
    }


def _quality_gates() -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="rta-public-gates-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        source = root / "state.md"
        source.write_text("The release gate is enabled.\n", encoding="utf-8")
        conn = connect(Path(tmp) / "brain.sqlite")
        try:
            init_project(conn, "gates", str(root))
            ingest_repo(conn, root, project="gates")
            source.write_text("The release gate is disabled.\n", encoding="utf-8")
            stale = stale_check(conn, project="gates", deep=True)
            stale_rejection = float(stale["state"] == "stale" and stale["changed"] == 1)

            remember(conn, "The guarded feature is enabled", project="gates")
            remember(conn, "The guarded feature is disabled", project="gates")
            reflected = reflect(conn, project="gates")
            contradiction_detection = float(reflected["contradictions_flagged"] == 2)

            save_checkpoint(
                conn, "gates", "Ship the verified build", verified_evidence="Focused checks passed",
                remaining_gaps="Operator review", next_action="Run browser proof",
                prohibited_repetition="Do not repeat unrelated scans",
            )
            continuation = build_continuation_prompt(conn, project="gates")
            continuation_success = float(
                "Ship the verified build" in continuation and "Run browser proof" in continuation
            )

            create_policy(
                conn, project="gates", kind="required_check", statement="Privacy proof is required",
                effect="block", action_contains="publish", required_check="privacy-proof",
                pramana="pratyaksha", confidence=0.95,
                provenance={"source_path": "state.md", "source_hash": "synthetic-proof", "verification_status": "verified"},
            )
            blocked = preflight(conn, project="gates", action="publish release")
            allowed = preflight(
                conn, project="gates", action="publish release", completed_checks=["privacy-proof"],
            )
            governance_accuracy = float(blocked["decision"] == "block" and allowed["decision"] == "allow")
        finally:
            conn.close()
    return {
        "stale_rejection": stale_rejection,
        "contradiction_detection": contradiction_detection,
        "continuation_success": continuation_success,
        "governance_accuracy": governance_accuracy,
    }


def run_public_benchmark(
    dataset: Path,
    *,
    include_semantic: bool = False,
    semantic_model: str = "all-MiniLM-L6-v2",
) -> dict:
    payload, digest = _load_dataset(Path(dataset))
    modes = {
        "no_memory": _run_mode(payload, "no_memory"),
        "lexical": _run_mode(payload, "lexical"),
        "hash_hybrid": _run_mode(payload, "hash_hybrid"),
        "optional_semantic": {
            "status": "not_requested",
            "provider": "sentence-transformers",
            "model": semantic_model,
        },
    }
    if include_semantic:
        try:
            metrics = _run_mode(payload, "sentence-transformers", semantic_model)
        except (ImportError, RuntimeError):
            modes["optional_semantic"] = {
                "status": "unavailable",
                "provider": "sentence-transformers",
                "model": semantic_model,
                "reason": "Optional local Sentence Transformers provider or model is unavailable.",
            }
        else:
            modes["optional_semantic"] = {
                "status": "ok", "provider": "sentence-transformers", "model": semantic_model, **metrics,
            }
    return {
        "schema_version": 1,
        "dataset": str(payload.get("name") or "public corpus"),
        "dataset_digest": digest,
        "corpus": {"documents": len(payload["documents"]), "queries": len(payload["queries"]), "synthetic": True},
        "modes": modes,
        "quality_gates": _quality_gates(),
    }


def _metric(value) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    return "NA"


def benchmark_report_markdown(result: dict) -> str:
    """Render a bounded, shareable report for the synthetic public benchmark."""
    corpus = result.get("corpus") or {}
    modes = result.get("modes") or {}
    gates = result.get("quality_gates") or {}
    lines = [
        "# Rta-Smriti Public Benchmark",
        "",
        "This report summarizes the packaged synthetic reproducibility and regression harness. "
        "It is not external proof of superiority over other memory systems.",
        "",
        f"- Dataset: `{result.get('dataset', 'public corpus')}`",
        f"- Dataset digest: `{result.get('dataset_digest', 'unknown')}`",
        f"- Corpus: {int(corpus.get('documents') or 0)} documents, {int(corpus.get('queries') or 0)} queries",
        f"- Synthetic: {bool(corpus.get('synthetic'))}",
        "",
        "| Mode | Status | NDCG@K | Recall@K | MRR@K | Precision@K | P50 ms | P95 ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("no_memory", "lexical", "hash_hybrid", "optional_semantic"):
        metrics = modes.get(name) or {}
        status = str(metrics.get("status") or "ok")
        latency = metrics.get("latency_ms") if isinstance(metrics.get("latency_ms"), dict) else {}
        lines.append(
            "| "
            + " | ".join((
                name,
                status,
                _metric(metrics.get("ndcg_at_k")),
                _metric(metrics.get("recall_at_k")),
                _metric(metrics.get("mrr_at_k")),
                _metric(metrics.get("precision_at_k")),
                _metric(latency.get("p50")),
                _metric(latency.get("p95")),
            ))
            + " |"
        )
    lines.extend([
        "",
        "## Quality Gates",
        "",
        "| Gate | Score |",
        "| --- | ---: |",
    ])
    for name in sorted(gates):
        lines.append(f"| {name} | {_metric(gates[name])} |")
    lines.extend([
        "",
        "Optional Sentence Transformers comparison is reported only when explicitly requested and available locally.",
        "No private repository content, local home paths, API keys, or credentials are required by this corpus.",
        "",
    ])
    return "\n".join(lines)


def write_benchmark_report(result: dict, output: Path) -> dict:
    requested = Path(output).expanduser()
    if requested.is_symlink():
        raise ValueError("refusing to replace a linked benchmark report")
    destination = requested.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        stat = destination.stat()
        if destination.is_symlink() or stat.st_nlink > 1:
            raise ValueError("refusing to replace a linked benchmark report")
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(benchmark_report_markdown(result))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"status": "ok", "path": str(destination), "format": "markdown"}
