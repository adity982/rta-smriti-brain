"""Run portable smoke checks against the current platform's standalone binary."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def run(executable: Path, *arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *arguments], input=stdin, text=True, capture_output=True, check=True, timeout=30
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    executable = (root / "dist" / ("rta-brain.exe" if os.name == "nt" else "rta-brain")).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"standalone executable is missing: {executable}")
    version = run(executable, "--version").stdout.strip()
    health = json.loads(run(executable, "--json", "doctor").stdout)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        brains = root / "brains"
        project.mkdir()
        source = project / "main.py"
        source.write_text("VALUE = 1\n", encoding="utf-8")
        bootstrap = json.loads(
            run(
                executable, "--json", "bootstrap-project", str(project),
                "--project", "smoke", "--brain-dir", str(brains),
            ).stdout
        )
        db_path = Path(bootstrap["db_path"])
        request = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        response = json.loads(
            run(executable, "mcp-server", "--db", str(db_path), "--project", "smoke", stdin=request).stdout
        )
        watcher = json.loads(
            run(
                executable, "--db", str(db_path), "--json", "watcher", "start", str(project),
                "--project", "smoke", "--interval", "0.2",
            ).stdout
        )
        try:
            source.write_text("VALUE = 2\n", encoding="utf-8")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                freshness = json.loads(
                    run(executable, "--db", str(db_path), "--json", "stale-check", "--project", "smoke").stdout
                )
                if freshness["state"] == "fresh":
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError(f"standalone watcher did not refresh the project: {freshness}")
        finally:
            stopped = json.loads(
                run(executable, "--db", str(db_path), "--json", "watcher", "stop", "--project", "smoke").stdout
            )
    if (
        "0.4.0a1" not in version
        or health.get("status") != "ok"
        or response.get("result") != {}
        or watcher.get("state") != "running"
        or stopped.get("state") != "stopped"
    ):
        raise RuntimeError("standalone binary smoke contract failed")
    print("Standalone binary smoke passed: CLI, SQLite/FTS, MCP dispatch, and background sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
