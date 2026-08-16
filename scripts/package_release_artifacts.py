"""Stage versioned release artifacts and a verified SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def platform_label() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError(f"unsupported release platform: {sys.platform}")


def architecture_label() -> str:
    machine = platform.machine().lower()
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }.get(machine, machine or "unknown")


def project_version() -> str:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(metadata["project"]["version"])


def run(command: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True, timeout=300)


def stage_artifacts(output: Path, include_wheel: bool) -> dict:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"artifact output already exists: {output}")
    output.mkdir(parents=True)

    source_name = "rta-brain.exe" if os.name == "nt" else "rta-brain"
    source = (ROOT / "dist" / source_name).resolve()
    if not source.is_file() or source.is_symlink() or source.stat().st_nlink != 1:
        raise FileNotFoundError(f"standalone release binary is missing or linked: {source}")

    version = project_version()
    suffix = ".exe" if os.name == "nt" else ""
    target = output / f"rta-brain-{version}-{platform_label()}-{architecture_label()}{suffix}"
    shutil.copyfile(source, target)
    if os.name != "nt":
        target.chmod(0o755)

    version_output = run([str(target), "--version"], cwd=output).stdout.strip()
    if version not in version_output:
        raise RuntimeError(f"packaged binary reports an unexpected version: {version_output}")

    if include_wheel:
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(output), "."])

    artifacts = sorted(path for path in output.iterdir() if path.is_file())
    manifest = output / "SHA256SUMS.txt"
    checksums = {path.name: file_sha256(path) for path in artifacts}
    manifest.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items()),
        encoding="ascii",
        newline="\n",
    )
    for name, expected in checksums.items():
        if file_sha256(output / name) != expected:
            raise RuntimeError(f"checksum verification failed after staging: {name}")
    return {
        "status": "ok",
        "version": version,
        "platform": platform_label(),
        "architecture": architecture_label(),
        "artifacts": checksums,
        "manifest": str(manifest),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release-artifacts")
    parser.add_argument("--include-wheel", action="store_true")
    args = parser.parse_args()
    print(json.dumps(stage_artifacts(args.output, args.include_wheel), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
