import os
import subprocess
from pathlib import Path


def canonical_root(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def same_root(left: str | Path, right: str | Path) -> bool:
    return canonical_root_key(left) == canonical_root_key(right)


def canonical_root_key(path: str | Path) -> str:
    return os.path.normcase(canonical_root(path))


def trusted_git_candidates() -> list[Path]:
    if os.name != "nt":
        values = ("/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git", "/opt/local/bin/git")
    else:
        roots = (
            os.environ.get("ProgramFiles") or "C:/Program Files",
            os.environ.get("ProgramFiles(x86)") or "C:/Program Files (x86)",
            os.environ.get("LocalAppData") or str(Path.home() / "AppData" / "Local"),
        )
        values = (
            str(Path(roots[0]) / "Git" / "cmd" / "git.exe"),
            str(Path(roots[0]) / "Git" / "bin" / "git.exe"),
            str(Path(roots[1]) / "Git" / "cmd" / "git.exe"),
            str(Path(roots[2]) / "Programs" / "Git" / "cmd" / "git.exe"),
        )
    candidates = []
    for value in values:
        candidate = Path(value)
        if candidate.is_file():
            candidates.append(candidate.resolve())
    return candidates


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    candidates = trusted_git_candidates()
    if not candidates:
        return None
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.run(
            [str(candidates[0]), "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
            creationflags=creationflags,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _stdout(root: Path, *args: str) -> str:
    result = _git(root, *args)
    return result.stdout.strip() if result and result.returncode == 0 else ""


def repository_state(root: str | Path | None) -> dict:
    if not root:
        return {
            "is_git_repo": False, "repository_root": None, "branch": None,
            "head": None, "dirty_files": 0, "remote": None,
        }
    requested = Path(root).expanduser().resolve()
    if not requested.exists() or not requested.is_dir():
        return {
            "is_git_repo": False, "repository_root": None, "branch": None,
            "head": None, "dirty_files": 0, "remote": None,
        }
    repository_root = _stdout(requested, "rev-parse", "--show-toplevel")
    if not repository_root:
        return {
            "is_git_repo": False, "repository_root": None, "branch": None,
            "head": None, "dirty_files": 0, "remote": None,
        }
    git_root = Path(repository_root).resolve()
    branch = _stdout(git_root, "symbolic-ref", "--quiet", "--short", "HEAD") or "detached"
    head = _stdout(git_root, "rev-parse", "--short=12", "HEAD") or None
    status = _stdout(git_root, "status", "--porcelain=v1", "--untracked-files=all")
    remote = _stdout(git_root, "remote", "get-url", "origin") or None
    return {
        "is_git_repo": True,
        "repository_root": str(git_root),
        "branch": branch,
        "head": head,
        "dirty_files": len([line for line in status.splitlines() if line.strip()]),
        "remote": remote,
    }
