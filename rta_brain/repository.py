import os
import re
import subprocess
import uuid
from pathlib import Path


IDENTITY_DIR = ".rta-smriti"
IDENTITY_FILE = "brain_id"
GIT_IDENTITY_FILE = "rta-smriti-brain-id"


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
        if candidate.is_absolute() and candidate.is_file():
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


def _git_layout(root: Path) -> tuple[Path, Path, Path] | None:
    current = root.resolve()
    for candidate_root in (current, *current.parents):
        marker = candidate_root / ".git"
        if marker.is_dir():
            git_dir = marker.resolve()
        elif marker.is_file():
            try:
                line = marker.read_text(encoding="utf-8", errors="strict").strip()
            except OSError:
                continue
            if not line.lower().startswith("gitdir:"):
                continue
            git_dir = Path(line.split(":", 1)[1].strip())
            if not git_dir.is_absolute():
                git_dir = candidate_root / git_dir
            git_dir = git_dir.resolve()
        else:
            continue
        common_dir = git_dir
        common_marker = git_dir / "commondir"
        if common_marker.is_file():
            value = common_marker.read_text(encoding="utf-8", errors="ignore").strip()
            if value:
                common_dir = Path(value)
                if not common_dir.is_absolute():
                    common_dir = git_dir / common_dir
                common_dir = common_dir.resolve()
        return candidate_root.resolve(), git_dir, common_dir
    return None


def _read_ref(common_dir: Path, ref_name: str) -> str | None:
    ref_path = (common_dir / ref_name).resolve()
    try:
        ref_path.relative_to(common_dir.resolve())
        value = ref_path.read_text(encoding="ascii", errors="strict").strip()
    except (OSError, ValueError):
        value = ""
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        return value.lower()
    try:
        lines = (common_dir / "packed-refs").read_text(encoding="ascii", errors="ignore").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if not line or line.startswith(("#", "^")):
            continue
        sha, _, name = line.partition(" ")
        if name == ref_name and re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
            return sha.lower()
    return None


def _native_head(git_dir: Path, common_dir: Path) -> tuple[str | None, str | None]:
    try:
        value = (git_dir / "HEAD").read_text(encoding="ascii", errors="strict").strip()
    except OSError:
        return None, None
    if value.startswith("ref:"):
        ref_name = value.split(":", 1)[1].strip()
        return ref_name.rsplit("/", 1)[-1], _read_ref(common_dir, ref_name)
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", value):
        return "detached", value.lower()
    return None, None


def _origin_remote(common_dir: Path) -> str | None:
    try:
        config = (common_dir / "config").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r'(?ms)^\s*\[remote\s+"origin"\]\s*$.*?^\s*url\s*=\s*(.+?)\s*$', config)
    return match.group(1).strip() if match else None


def _marker_identity(root: Path, create: bool) -> str | None:
    marker_dir = root / IDENTITY_DIR
    marker = marker_dir / IDENTITY_FILE
    if marker.exists():
        if marker.is_symlink() or marker.stat().st_nlink > 1:
            raise ValueError(f"refusing linked repository identity marker: {marker}")
        value = marker.read_text(encoding="ascii", errors="strict").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ValueError(f"invalid repository identity marker: {marker}")
        return f"local:{value}"
    if not create:
        return None
    marker_dir.mkdir(parents=True, exist_ok=True)
    value = uuid.uuid4().hex
    try:
        with marker.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(value + "\n")
    except FileExistsError:
        return _marker_identity(root, create=False)
    return f"local:{value}"


def _git_marker_identity(common_dir: Path, create: bool) -> str | None:
    marker = common_dir / GIT_IDENTITY_FILE
    if marker.exists():
        if marker.is_symlink() or marker.stat().st_nlink > 1:
            raise ValueError(f"refusing linked repository identity marker: {marker}")
        value = marker.read_text(encoding="ascii", errors="strict").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ValueError(f"invalid repository identity marker: {marker}")
        return f"git-local:{value}"
    if not create:
        return None
    value = uuid.uuid4().hex
    try:
        with marker.open("x", encoding="ascii", newline="\n") as stream:
            stream.write(value + "\n")
    except FileExistsError:
        return _git_marker_identity(common_dir, create=False)
    return f"git-local:{value}"


def repository_identity(root: str | Path, create_marker: bool = True) -> str:
    requested = Path(root).expanduser().resolve()
    if not requested.exists() or not requested.is_dir():
        raise ValueError(f"repository root does not exist or is not a directory: {requested}")
    existing_local_marker = _marker_identity(requested, create=False)
    if existing_local_marker:
        return existing_local_marker
    layout = _git_layout(requested)
    if layout:
        repository_root, _git_dir, common_dir = layout
        existing_git_marker = _git_marker_identity(common_dir, create=False)
        if existing_git_marker:
            return existing_git_marker
        first_commits = _stdout(repository_root, "rev-list", "--max-parents=0", "HEAD").splitlines()
        if first_commits and re.fullmatch(r"[0-9a-fA-F]{40,64}", first_commits[0]):
            return f"git:{first_commits[0].lower()}"
        marker = _git_marker_identity(common_dir, create=create_marker)
        if marker:
            return marker
    marker = _marker_identity(requested, create=create_marker)
    if not marker:
        raise ValueError("repository identity is unavailable")
    return marker


def repository_state(root: str | Path | None, include_worktree: bool = True) -> dict:
    empty = {
        "is_git_repo": False, "repository_root": None, "branch": None,
        "head": None, "dirty_files": None, "remote": None, "head_source": None,
    }
    if not root:
        return empty
    requested = Path(root).expanduser().resolve()
    if not requested.exists() or not requested.is_dir():
        return empty
    layout = _git_layout(requested)
    if not layout:
        return empty
    git_root, git_dir, common_dir = layout
    branch, full_head = _native_head(git_dir, common_dir)
    dirty_files = None
    if include_worktree:
        status = _stdout(git_root, "status", "--porcelain=v1", "--untracked-files=all")
        dirty_files = len([line for line in status.splitlines() if line.strip()])
    return {
        "is_git_repo": True,
        "repository_root": str(git_root),
        "branch": branch or "unknown",
        "head": full_head[:12] if full_head else None,
        "dirty_files": dirty_files,
        "remote": _origin_remote(common_dir),
        "head_source": "native",
    }
