from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_temporal_truth_dashboard_is_wired_to_real_operator_api():
    source = (ROOT / "dashboard-src" / "src" / "main.jsx").read_text(
        encoding="utf-8"
    )
    styles = (ROOT / "dashboard-src" / "src" / "styles.css").read_text(
        encoding="utf-8"
    )
    assert "function TemporalTruthWorkspace" in source
    assert 'api(`/api/truth?' in source
    assert 'api("/api/truth"' in source
    assert "Truth Timeline" in source
    assert "Contradictions" in source
    assert "Validator Health" in source
    assert ".truthWorkspace" in styles
    assert ".truthTimeline" in styles
