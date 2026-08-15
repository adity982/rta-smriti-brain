import subprocess
import sys
import tempfile
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rta-smriti-wheel-build-") as tmp:
        smoke_root = Path(tmp)
        wheel_dir = smoke_root / "wheel"
        environment = smoke_root / "venv"
        wheel_dir.mkdir()

        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir), "."])
        venv.EnvBuilder(with_pip=True).create(environment)

        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        cli = scripts / ("rta-brain.exe" if sys.platform == "win32" else "rta-brain")
        wheel = next(wheel_dir.glob("*.whl"))

        run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)])
        run([str(python), str(ROOT / "scripts" / "installed_distribution_smoke.py"), "--cli", str(cli)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
