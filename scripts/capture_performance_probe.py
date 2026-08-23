"""Measure bounded universal-capture operations with privacy-safe synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rta_brain.capture import (
    append_event,
    read_capture_replay,
    register_policy,
    register_source,
    verify_journal,
)
from rta_brain.capture_adapters import normalize_capture_event
from rta_brain.capture_spool import CaptureSpool, SpoolLimits
from rta_brain.capture_types import (
    DEFAULT_MAX_EVENT_BYTES,
    CapturePolicy,
    CaptureSource,
    NormalizedEvent,
)
from rta_brain.db import connect, init_project


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def latency_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "p50": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "p99": round(percentile(values, 0.99), 3),
        "samples": len(values),
    }


def measure_normalization(size: int, samples: int) -> dict:
    text = "S" * max(1, size - 128)
    latencies = []
    failures = 0
    for index in range(samples):
        started = perf_counter()
        try:
            normalized = normalize_capture_event(
                "generic",
                {
                    "type": "tool_complete",
                    "tool": "synthetic.probe",
                    "status": "ok",
                    "summary": text,
                },
                source_cursor=str(index + 1),
                observed_at="2026-08-22T12:00:00+00:00",
                session_id="synthetic-session",
            )
            if normalized is None:
                failures += 1
        except (TypeError, ValueError):
            failures += 1
        latencies.append((perf_counter() - started) * 1_000)
    return {
        "input_bytes": size,
        "latency_ms": latency_summary(latencies),
        "failures": failures,
    }


def measure_journal(event_count: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="rta-capture-probe-") as temporary:
        base = Path(temporary)
        root = base / "repo"
        root.mkdir()
        database = base / "brain.sqlite"
        conn = connect(database)
        policy = CapturePolicy.continuity()
        source = CaptureSource(
            source_id="synthetic-probe",
            adapter="generic",
            adapter_version="1",
            installation_scope="api",
            config_fingerprint=hashlib.sha256(b"synthetic-capture-probe").hexdigest(),
        )
        try:
            init_project(conn, "synthetic", str(root))
            register_policy(
                conn,
                project="synthetic",
                active_root=root,
                policy_id="continuity",
                policy_version=1,
                policy=policy,
            )
            register_source(
                conn,
                project="synthetic",
                active_root=root,
                source=source,
                policy_digest=policy.digest,
            )
            started = perf_counter()
            for index in range(1, event_count + 1):
                append_event(
                    conn,
                    project="synthetic",
                    active_root=root,
                    source_id=source.source_id,
                    event=NormalizedEvent(
                        event_name="tool.completed.v1",
                        session_id="synthetic-session",
                        source_cursor=str(index),
                        observed_at="2026-08-22T12:00:00+00:00",
                        attributes={
                            "tool": "synthetic.probe",
                            "status": "ok",
                            "summary": f"event-{index}",
                        },
                    ),
                    idempotency_key=f"synthetic:{index}",
                    cursor_kind="sequence",
                    original_bytes=128,
                )
            append_seconds = perf_counter() - started

            replayed = 0
            cursor = 0
            replay_latencies = []
            replay_started = perf_counter()
            while replayed < event_count:
                started = perf_counter()
                page = read_capture_replay(
                    conn,
                    project="synthetic",
                    mode="chronological",
                    after_sequence=cursor,
                    limit=min(500, event_count - replayed),
                )
                replay_latencies.append((perf_counter() - started) * 1_000)
                events = page["events"]
                if not events:
                    break
                replayed += len(events)
                cursor = int(events[-1]["project_sequence"])
            replay_seconds = perf_counter() - replay_started

            measured_events = 0
            measured_cursor = 0
            tracemalloc.start()
            while measured_events < event_count:
                page = read_capture_replay(
                    conn,
                    project="synthetic",
                    mode="chronological",
                    after_sequence=measured_cursor,
                    limit=min(500, event_count - measured_events),
                )
                events = page["events"]
                if not events:
                    break
                measured_events += len(events)
                measured_cursor = int(events[-1]["project_sequence"])
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            integrity = verify_journal(conn, project="synthetic")
        finally:
            conn.close()

        return {
            "events": event_count,
            "append_seconds": round(append_seconds, 3),
            "append_events_per_second": round(
                event_count / max(append_seconds, 0.000001), 3
            ),
            "replayed_events": replayed,
            "memory_probe_replayed_events": measured_events,
            "replay_total_seconds": round(replay_seconds, 3),
            "replay_page_latency_ms": latency_summary(replay_latencies),
            "journal_verified": bool(integrity["chain_valid"]),
            "database_bytes": database.stat().st_size,
            "peak_python_allocation_bytes": peak_bytes,
        }


def measure_backpressure() -> dict:
    with tempfile.TemporaryDirectory(prefix="rta-capture-spool-probe-") as temporary:
        database = Path(temporary) / "brain.sqlite"
        database.touch()
        spool = CaptureSpool(
            database,
            limits=SpoolLimits(
                max_record_bytes=4_096,
                max_source_bytes=32_768,
                max_source_records=4,
                max_total_bytes=32_768,
                max_total_records=4,
            ),
        )
        receipts = [
            spool.publish(
                "synthetic-source",
                {"sequence": index},
                project="synthetic-project",
                allowed_fields=frozenset({"sequence"}),
            )
            for index in range(1, 6)
        ]
        return {
            "accepted": sum(receipt.status == "stored" for receipt in receipts),
            "rejected": sum(receipt.status != "stored" for receipt in receipts),
            "fail_closed": receipts[-1].status != "stored",
        }


def run_probe(
    event_count: int = 10_000, hook_samples: int = 100, assert_bounds: bool = False
) -> dict:
    if not 1 <= event_count <= 50_000:
        raise ValueError("event_count must be between 1 and 50,000")
    if not 5 <= hook_samples <= 10_000:
        raise ValueError("hook_samples must be between 5 and 10,000")
    payload = {
        "schema_version": 1,
        "fixture": "synthetic-universal-capture",
        "environment": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
            "python": platform.python_version(),
        },
        "hook_normalization": [
            measure_normalization(size, hook_samples)
            for size in (1_024, 65_536, DEFAULT_MAX_EVENT_BYTES)
        ],
        "journal": measure_journal(event_count),
        "backpressure": measure_backpressure(),
    }
    if assert_bounds:
        if any(item["failures"] for item in payload["hook_normalization"]):
            raise AssertionError(
                "capture normalization rejected accepted synthetic input"
            )
        if any(
            item["latency_ms"]["p99"] > 250 for item in payload["hook_normalization"]
        ):
            raise AssertionError(
                "capture normalization exceeded the generous p99 regression bound"
            )
        if (
            payload["journal"]["replayed_events"] != event_count
            or not payload["journal"]["journal_verified"]
        ):
            raise AssertionError(
                "capture journal replay or integrity verification was incomplete"
            )
        if payload["journal"]["memory_probe_replayed_events"] != event_count:
            raise AssertionError("capture replay memory probe was incomplete")
        if payload["journal"]["replay_total_seconds"] > 2:
            raise AssertionError(
                "capture replay exceeded the 2 second 10k-event budget"
            )
        if payload["journal"]["peak_python_allocation_bytes"] > 200 * 1024 * 1024:
            raise AssertionError(
                "capture replay exceeded the 200 MiB peak allocation budget"
            )
        if not payload["backpressure"]["fail_closed"]:
            raise AssertionError(
                "capture spool did not fail closed at its record budget"
            )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--hook-samples", type=int, default=100)
    parser.add_argument("--assert-bounds", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run_probe(
        args.events, args.hook_samples, assert_bounds=args.assert_bounds
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8", newline="\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
