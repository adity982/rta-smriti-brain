"""Bounded, non-shell validator adapters for temporal truth claims."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from .repository import canonical_root, repository_state, run_git_inspection


def safe_project_file(root: str | Path, relative_path: str) -> Path:
    canonical = Path(canonical_root(root))
    candidate = canonical.joinpath(*Path(relative_path).parts)
    current = canonical
    for part in Path(relative_path).parts:
        if part in {"", ".", ".."}:
            raise ValueError("validator path contains an unsafe segment")
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("validator path must not traverse a symbolic link")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(canonical)
    except ValueError as exc:
        raise ValueError("validator path escapes the canonical root") from exc
    return resolved


def stable_file_sha256(path: Path, *, maximum_bytes: int = 64 * 1024 * 1024) -> str:
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise FileNotFoundError(str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink != 1:
            raise ValueError("validator files must not be hard linked")
        if before.st_size > maximum_bytes:
            raise ValueError("validator file exceeds the 64 MiB bound")
        total = 0
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > maximum_bytes:
                raise ValueError("validator file exceeds the 64 MiB bound")
            digest.update(block)
        after = os.fstat(stream.fileno())
        if after.st_nlink != 1:
            raise ValueError("validator files must not be hard linked")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("validator file changed while it was read")
    return digest.hexdigest()


def stable_file_bytes(path: Path, *, maximum_bytes: int) -> bytes:
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise FileNotFoundError(str(path))
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink != 1:
            raise ValueError("validator files must not be hard linked")
        if before.st_size > maximum_bytes:
            raise ValueError("validator file exceeds its byte bound")
        data = stream.read(maximum_bytes + 1)
        after = os.fstat(stream.fileno())
        if after.st_nlink != 1:
            raise ValueError("validator files must not be hard linked")
    if len(data) > maximum_bytes:
        raise ValueError("validator file exceeds its byte bound")
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("validator file changed while it was read")
    return data


def json_pointer(document: Any, pointer: str) -> Any:
    current = document
    if pointer == "":
        return current
    for encoded in pointer.split("/")[1:]:
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise KeyError(pointer)
    return current


def git_anchor_state(active_root: str | Path) -> dict[str, Any]:
    root = canonical_root(active_root)
    head_result = run_git_inspection(Path(root), "rev-parse", "--verify", "HEAD")
    status_result = run_git_inspection(
        Path(root), "status", "--porcelain=v1", "-z", "--untracked-files=normal"
    )
    if (
        head_result is None or status_result is None
        or head_result.returncode != 0 or status_result.returncode != 0
    ):
        raise ValueError(
            "repository anchor requires an available verified Git checkout"
        )
    head_stdout = head_result.stdout.encode("utf-8", errors="strict")
    status_stdout = status_result.stdout.encode("utf-8", errors="surrogatepass")
    if len(head_stdout) > 128 or len(status_stdout) > 1024 * 1024:
        raise ValueError("repository anchor Git output exceeded its bound")
    commit = head_result.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("repository anchor could not resolve a full Git commit")
    state = repository_state(root)
    return {
        "branch": state.get("branch"),
        "commit": commit,
        "dirty_digest": hashlib.sha256(status_stdout).hexdigest(),
        "dirty_files": state.get("dirty_files"),
    }


def evaluate_validator(
    validator_type: str,
    config: dict[str, Any],
    *,
    active_root: str | Path,
    allow_command: bool,
    trusted_executables: list[str] | tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    if validator_type == "file_sha256":
        path = safe_project_file(active_root, config["path"])
        try:
            actual = stable_file_sha256(path)
        except FileNotFoundError:
            return "fail", {"path": config["path"], "reason": "missing"}
        expected = config["sha256"]
        return (
            "pass" if actual == expected else "fail",
            {"path": config["path"], "expected_sha256": expected, "actual_sha256": actual},
        )
    if validator_type == "file_exists":
        path = safe_project_file(active_root, config["path"])
        exists = (
            path.exists() and path.is_file() and not path.is_symlink()
            and path.stat().st_nlink == 1
        )
        return "pass" if exists else "fail", {"path": config["path"], "exists": exists}
    if validator_type == "json_pointer_equals":
        path = safe_project_file(active_root, config["path"])
        try:
            document = json.loads(stable_file_bytes(path, maximum_bytes=4 * 1024 * 1024))
            actual = json_pointer(document, config["pointer"])
        except FileNotFoundError:
            return "fail", {"path": config["path"], "reason": "missing"}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "fail", {"path": config["path"], "reason": "invalid_json"}
        except KeyError:
            return "fail", {"path": config["path"], "reason": "pointer_missing"}
        passed = actual == config["equals"]
        return "pass" if passed else "fail", {
            "path": config["path"], "pointer": config["pointer"], "matched": passed,
        }
    if validator_type == "sqlite_integrity":
        path = safe_project_file(active_root, config["path"])
        if (
            not path.exists() or not path.is_file() or path.is_symlink()
            or path.stat().st_nlink != 1
        ):
            return "fail", {"path": config["path"], "reason": "missing"}
        try:
            check = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2.0)
            try:
                result = str(check.execute("PRAGMA quick_check").fetchone()[0])
            finally:
                check.close()
        except sqlite3.Error as exc:
            return "fail", {
                "path": config["path"], "reason": "sqlite_error",
                "error_type": type(exc).__name__,
            }
        return "pass" if result == "ok" else "fail", {
            "path": config["path"], "quick_check": result,
        }
    if validator_type == "git_head_equals":
        state = git_anchor_state(active_root)
        passed = state["commit"] == config["commit"]
        return "pass" if passed else "fail", {
            "expected_commit": config["commit"], "actual_commit": state["commit"],
        }
    if validator_type == "git_clean_state":
        state = git_anchor_state(active_root)
        actual_clean = int(state["dirty_files"] or 0) == 0
        passed = actual_clean is bool(config["clean"])
        return "pass" if passed else "fail", {
            "expected_clean": bool(config["clean"]), "actual_clean": actual_clean,
        }
    if validator_type == "command_exit" and not allow_command:
        return "unavailable", {"reason": "command validator capability is disabled"}
    if validator_type == "command_exit":
        executable = Path(config["argv"][0]).expanduser().resolve()
        trusted = {
            os.path.normcase(str(Path(value).expanduser().resolve()))
            for value in trusted_executables
        }
        if os.path.normcase(str(executable)) not in trusted:
            return "unavailable", {"reason": "executable is not operator-trusted"}
        if not executable.is_file() or executable.is_symlink():
            return "unavailable", {"reason": "trusted executable is not a safe regular file"}
        environment = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME"}
        }
        environment["PYTHONIOENCODING"] = "utf-8"
        kwargs: dict[str, Any] = {
            "cwd": canonical_root(active_root), "env": environment,
            "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL, "timeout": float(config["timeout_seconds"]),
            "check": False, "shell": False,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run([str(executable), *config["argv"][1:]], **kwargs)
        except subprocess.TimeoutExpired:
            return "error", {"reason": "command timed out"}
        except OSError as exc:
            return "error", {"reason": f"command could not start: {type(exc).__name__}"}
        exit_code = int(completed.returncode)
        return "pass" if exit_code == 0 else "fail", {
            "exit_code": exit_code, "output_captured": False,
        }
    return "unavailable", {"reason": f"validator adapter unavailable: {validator_type}"}
