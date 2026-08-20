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
    benchmark = json.loads(run(executable, "benchmark", "--json").stdout)
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
        managed_port = 0
        managed = json.loads(
            run(
                executable, "console", "start", "--brain-dir", str(brains),
                "--port", str(managed_port), "--no-open", "--json",
            ).stdout
        )
        try:
            managed_status = json.loads(
                run(executable, "console", "status", "--brain-dir", str(brains), "--json").stdout
            )
            managed_open = json.loads(
                run(
                    executable, "console", "open", "--brain-dir", str(brains), "--no-open", "--json",
                ).stdout
            )
        finally:
            managed_stopped = json.loads(
                run(executable, "console", "stop", "--brain-dir", str(brains), "--json").stdout
            )
    if (
        "0.5.0a1" not in version
        or health.get("status") != "ok"
        or not benchmark.get("corpus", {}).get("synthetic")
        or set(benchmark.get("modes", {})) != {"no_memory", "lexical", "hash_hybrid", "optional_semantic"}
        or benchmark.get("modes", {}).get("optional_semantic", {}).get("status") != "not_requested"
        or response.get("result") != {}
        or watcher.get("state") != "running"
        or stopped.get("state") != "stopped"
        or managed.get("state") != "running"
        or managed_status.get("state") != "running"
        or "url" in managed_status
        or "#token=" not in managed_open.get("url", "")
        or managed_stopped.get("state") != "stopped"
    ):
        raise RuntimeError("standalone binary smoke contract failed")
    print(
        "Standalone binary smoke passed: CLI, SQLite/FTS, MCP dispatch, public benchmark, "
        "background sync, and managed console lifecycle."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
