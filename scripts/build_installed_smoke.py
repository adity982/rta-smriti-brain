import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from package_release_artifacts import assert_wheel_static_assets, clean_wheel_build


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        rendered = subprocess.list2cmdline(command)
        raise RuntimeError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rta-smriti-wheel-build-") as tmp:
        smoke_root = Path(tmp)
        wheel_dir = smoke_root / "wheel"
        environment = smoke_root / "venv"
        wheel_dir.mkdir()

        clean_wheel_build()
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), "."])
        venv.EnvBuilder(with_pip=True).create(environment)

        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        cli = scripts / ("rta-brain.exe" if sys.platform == "win32" else "rta-brain")
        wheel = next(wheel_dir.glob("*.whl"))
        assert_wheel_static_assets(wheel)

        run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)])
        expected_version = run([
            str(python), "-c",
            "from importlib.metadata import version; print(version('rta-smriti-brain'))",
        ], cwd=smoke_root).stdout.strip()
        run([str(python), str(ROOT / "scripts" / "installed_distribution_smoke.py"), "--cli", str(cli)])
        run([
            str(python), "-m", "pip", "install", "--no-deps", "--upgrade", "--force-reinstall", str(wheel),
        ])
        version = run([str(cli), "--version"], cwd=smoke_root).stdout.strip()
        if expected_version not in version:
            raise AssertionError(f"upgraded CLI reported an unexpected version: {version}")

        run([str(python), "-m", "pip", "uninstall", "-y", "rta-smriti-brain"])
        import_probe = run([
            str(python), "-c",
            "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('rta_brain') is None else 1)",
        ], cwd=smoke_root)
        if import_probe.returncode != 0 or cli.exists():
            raise AssertionError("uninstall left an importable package or CLI entry point")

        print('{"status":"ok","lifecycle":["install","upgrade","uninstall"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
