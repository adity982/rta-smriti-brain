"""Run portable smoke checks against the current platform's standalone binary."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
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
        db_path = Path(tmp) / "binary-smoke.sqlite"
        request = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        response = json.loads(
            run(executable, "mcp-server", "--db", str(db_path), "--project", "smoke", stdin=request).stdout
        )
    if "0.4.0a1" not in version or health.get("status") != "ok" or response.get("result") != {}:
        raise RuntimeError("standalone binary smoke contract failed")
    print("Standalone binary smoke passed: CLI, SQLite/FTS, and MCP dispatch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
