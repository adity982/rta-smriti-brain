import json

from scripts.capture_performance_probe import run_probe


def test_capture_probe_is_bounded_reproducible_and_private_safe():
    report = run_probe(event_count=24, hook_samples=5, assert_bounds=True)

    assert report["fixture"] == "synthetic-universal-capture"
    assert report["journal"]["replayed_events"] == 24
    assert report["journal"]["memory_probe_replayed_events"] == 24
    assert report["journal"]["replay_total_seconds"] <= 2
    assert report["journal"]["peak_python_allocation_bytes"] <= 200 * 1024 * 1024
    assert report["journal"]["journal_verified"] is True
    assert report["backpressure"]["fail_closed"] is True
    serialized = json.dumps(report, sort_keys=True)
    assert "rta-capture-probe-" not in serialized
    assert "Users\\" not in serialized
    assert "/home/" not in serialized


def test_capture_probe_replays_the_full_documented_page_limit():
    report = run_probe(event_count=500, hook_samples=5, assert_bounds=True)

    assert report["journal"]["replayed_events"] == 500
    assert report["journal"]["journal_verified"] is True
