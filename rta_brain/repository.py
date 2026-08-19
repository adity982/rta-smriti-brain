import os
import re
import subprocess
import tempfile
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


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_EXTERNAL_DIFF": "",
        "GCM_INTERACTIVE": "Never",
        "PAGER": "cat",
    })
    return environment


def _configured_command_keys(
    git: Path, root: Path, environment: dict[str, str],
) -> set[str] | None:
    try:
        result = subprocess.run(
            [
                str(git), "--no-pager", "-C", str(root), "config", "--null", "--name-only",
                "--get-regexp", r"^(filter\..*\.(clean|process|required)|diff\..*\.(command|textconv))$",
            ],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return {key.strip() for key in result.stdout.split("\0") if key.strip()}


def _disabled_executable_config(keys: set[str]) -> list[str]:
    drivers: set[tuple[str, str]] = set()
    for key in keys:
        match = re.fullmatch(
            r"(filter|diff)\.(.+)\.(clean|process|required|command|textconv)",
            key,
            flags=re.IGNORECASE,
        )
        if match:
            drivers.add((match.group(1).lower(), match.group(2)))
    options: list[str] = []
    for kind, driver in sorted(drivers):
        if kind == "filter":
            options.extend([
                "-c", f"filter.{driver}.clean=",
                "-c", f"filter.{driver}.process=",
                "-c", f"filter.{driver}.required=false",
            ])
        else:
            options.extend([
                "-c", f"diff.{driver}.command=",
                "-c", f"diff.{driver}.textconv=",
            ])
    return options


def _git_command(
    git: Path,
    root: Path,
    args: tuple[str, ...],
    *,
    hooks_path: Path,
    disable_hooks: bool,
    environment: dict[str, str],
) -> list[str]:
    command = [
        str(git), "--no-pager",
        "-c", "core.fsmonitor=false",
        "-c", "diff.external=",
        "-c", "core.pager=cat",
        "-c", "pager.status=false",
        "-c", "pager.config=false",
        "-c", "interactive.singleKey=false",
    ]
    if disable_hooks:
        command.extend(["-c", f"core.hooksPath={hooks_path}"])
    command_keys = _configured_command_keys(git, root, environment)
    if command_keys is None:
        raise ValueError("Git executable configuration could not be inspected safely")
    command.extend(_disabled_executable_config(command_keys))
    command.extend(["-C", str(root), *args])
    return command


def run_git_inspection(
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[str] | None:
    """Run trusted Git with repository-controlled executable features disabled."""
    candidates = trusted_git_candidates()
    if not candidates:
        return None
    resolved = Path(root).expanduser().resolve()
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    environment = _git_environment()
    with tempfile.TemporaryDirectory(prefix="rta-smriti-git-hooks-") as empty_hooks:
        try:
            command = _git_command(
                candidates[0], resolved, tuple(args), hooks_path=Path(empty_hooks),
                disable_hooks=True, environment=environment,
            )
            return subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=8,
                check=False,
                creationflags=creationflags,
                env=environment,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    return run_git_inspection(root, *args)


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


def verified_git_layout(root: Path) -> tuple[Path, Path, Path] | None:
    """Return native Git paths only when trusted Git reports the same layout."""
    layout = _git_layout(Path(root).expanduser().resolve())
    if not layout:
        return None
    repository_root, git_dir, common_dir = layout
    result = run_git_inspection(
        repository_root,
        "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-dir", "--git-common-dir",
    )
    if not result or result.returncode != 0:
        return None
    values = [Path(value).expanduser().resolve() for value in result.stdout.splitlines() if value.strip()]
    if len(values) != 3:
        return None
    reported = tuple(canonical_root_key(value) for value in values)
    expected = tuple(canonical_root_key(value) for value in layout)
    return layout if reported == expected else None


def configured_hooks_path(root: Path, common_dir: Path) -> Path | None:
    """Read core.hooksPath as data while the inspection process uses disabled hooks."""
    resolved_root = Path(root).expanduser().resolve()
    result = run_git_inspection(
        resolved_root, "config", "--null", "--path", "--get-all", "core.hooksPath",
    )
    if not result or result.returncode != 0:
        return None
    values = [value for value in result.stdout.split("\0") if value]
    if not values:
        return None
    configured_values = values[:-1]
    if not configured_values:
        return common_dir.resolve() / "hooks"
    configured = Path(configured_values[-1]).expanduser()
    if not configured.is_absolute():
        configured = resolved_root / configured
    return configured.resolve()


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
        # Normal mode reports untracked directories as one dirty entry and avoids
        # recursively walking generated trees during every dashboard refresh.
        status = _stdout(git_root, "status", "--porcelain=v1", "--untracked-files=normal")
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
