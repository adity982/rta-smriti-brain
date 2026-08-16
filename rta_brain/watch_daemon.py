"""Cross-platform background repository watcher with a polling fallback."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .db import connect, ingest_repo


_SPAWNED_PROCESSES: dict[str, subprocess.Popen] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "default"


def watcher_paths(db_path: Path, project: str) -> dict[str, Path]:
    database = db_path.expanduser().resolve()
    key = hashlib.sha256(f"{database}\0{project}".encode("utf-8")).hexdigest()[:12]
    control_dir = database.parent / ".rta-smriti-daemons"
    stem = f"{database.stem}-{_slug(project)}-{key}"
    return {
        "directory": control_dir,
        "state": control_dir / f"{stem}.json",
        "stop": control_dir / f"{stem}.stop",
        "lock": control_dir / f"{stem}.lock",
        "log": control_dir / f"{stem}.log",
    }


def _prepare_control_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"watcher control directory is not a safe directory: {path}")


def _write_json(path: Path, payload: dict) -> None:
    _prepare_control_dir(path.parent)
    if path.exists() and (path.is_symlink() or path.stat().st_nlink > 1):
        raise ValueError(f"refusing linked watcher state: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(40):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.025)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict | None:
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink > 1:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_safe_regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
    except OSError:
        return False


def _write_stop_request(path: Path) -> None:
    _prepare_control_dir(path.parent)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if not _is_safe_regular_file(path):
            raise ValueError(f"refusing linked watcher stop file: {path}")
        return
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
        stream.write("stop\n")


def _stop_requested(path: Path) -> bool:
    if not path.exists():
        return False
    if not _is_safe_regular_file(path):
        raise ValueError(f"refusing linked watcher stop file: {path}")
    return True


def _open_log(path: Path):
    _prepare_control_dir(path.parent)
    if path.exists() and not _is_safe_regular_file(path):
        raise ValueError(f"refusing linked watcher log: {path}")
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    return os.fdopen(descriptor, "a", encoding="utf-8", buffering=1)


def _process_alive(pid: int | None) -> bool:
    if not pid or int(pid) <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def watcher_status(db_path: Path, project: str) -> dict:
    paths = watcher_paths(db_path, project)
    payload = _read_json(paths["state"])
    if not payload:
        return {
            "status": "ok",
            "state": "stopped",
            "project": project,
            "db_path": str(db_path.expanduser().resolve()),
            "backend": None,
        }
    state = str(payload.get("state") or "unknown")
    if state in {"starting", "running", "stopping"} and not _process_alive(payload.get("pid")):
        state = "stale"
    return {"status": "ok", **payload, "state": state}


def _clear_stale_control(paths: dict[str, Path]) -> None:
    for key in ("state", "stop", "lock"):
        path = paths[key]
        if path.exists() and not path.is_symlink() and path.stat().st_nlink == 1:
            path.unlink(missing_ok=True)


def _worker_command(db_path: Path, root: Path, project: str, paths: dict[str, Path], interval: float) -> list[str]:
    suffix = [
        "_watch-worker",
        "--root", str(root),
        "--project", project,
        "--state-file", str(paths["state"]),
        "--stop-file", str(paths["stop"]),
        "--lock-file", str(paths["lock"]),
        "--interval", str(interval),
    ]
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--db", str(db_path), *suffix]
    return [str(Path(sys.executable).resolve()), "-m", "rta_brain.cli", "--db", str(db_path), *suffix]


def start_watcher(
    db_path: Path,
    root: Path,
    project: str,
    interval_seconds: float = 2.0,
    startup_timeout: float = 10.0,
) -> dict:
    database = db_path.expanduser().resolve()
    repository = root.expanduser().resolve()
    interval = float(interval_seconds)
    if not database.is_file() or database.is_symlink() or database.stat().st_nlink > 1:
        raise ValueError(f"brain database must be an existing unlinked file: {database}")
    if not repository.is_dir():
        raise ValueError(f"watch root does not exist or is not a directory: {repository}")
    if not 0.1 <= interval <= 3600:
        raise ValueError("watch interval must be between 0.1 and 3,600 seconds")
    paths = watcher_paths(database, project)
    _prepare_control_dir(paths["directory"])
    current = watcher_status(database, project)
    if current["state"] in {"starting", "running", "stopping"}:
        return current
    _clear_stale_control(paths)
    token = secrets_token = uuid.uuid4().hex
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    try:
        descriptor = os.open(paths["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("watcher start is already in progress") from exc
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
        stream.write(token_hash + "\n")
    env = {**os.environ, "RTA_SMIRTI_WATCH_TOKEN": secrets_token}
    creationflags = 0
    kwargs = {"start_new_session": True}
    if os.name == "nt":
        creationflags = 0x00000008 | 0x00000200 | 0x08000000
        kwargs = {}
    try:
        log_stream = _open_log(paths["log"])
    except Exception:
        paths["lock"].unlink(missing_ok=True)
        raise
    try:
        process = subprocess.Popen(
            _worker_command(database, repository, project, paths, interval),
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=log_stream,
            close_fds=True,
            env=env,
            creationflags=creationflags,
            **kwargs,
        )
    except Exception:
        paths["lock"].unlink(missing_ok=True)
        raise
    finally:
        log_stream.close()
    deadline = time.monotonic() + max(1.0, float(startup_timeout))
    while time.monotonic() < deadline:
        state = watcher_status(database, project)
        if state.get("token_hash") == token_hash and state["state"] == "running":
            _SPAWNED_PROCESSES[str(paths["state"])] = process
            return state
        if process.poll() is not None:
            break
        time.sleep(0.05)
    _write_stop_request(paths["stop"])
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    tail = ""
    try:
        tail = paths["log"].read_text(encoding="utf-8", errors="ignore")[-2_000:]
    except OSError:
        pass
    raise RuntimeError(f"watcher did not become ready within {startup_timeout:g} seconds{': ' + tail if tail else ''}")


def stop_watcher(db_path: Path, project: str, timeout: float = 10.0) -> dict:
    paths = watcher_paths(db_path, project)
    state = watcher_status(db_path, project)
    if state["state"] in {"stopped", "stale", "error"}:
        _clear_stale_control(paths)
        return {**state, "state": "stopped"}
    _prepare_control_dir(paths["directory"])
    _write_stop_request(paths["stop"])
    deadline = time.monotonic() + max(0.1, float(timeout))
    while time.monotonic() < deadline:
        state = watcher_status(db_path, project)
        if state["state"] in {"stopped", "stale", "error"}:
            process = _SPAWNED_PROCESSES.pop(str(paths["state"]), None)
            if process is not None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            return {**state, "state": "stopped" if state["state"] == "stale" else state["state"]}
        time.sleep(0.05)
    raise TimeoutError(f"watcher did not stop within {timeout:g} seconds")


def run_watcher_worker(
    db_path: Path,
    root: Path,
    project: str,
    state_file: Path,
    stop_file: Path,
    lock_file: Path,
    interval_seconds: float,
) -> int:
    token = os.environ.get("RTA_SMIRTI_WATCH_TOKEN", "")
    if not token:
        raise RuntimeError("watcher launch token is missing")
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    if not lock_file.is_file() or lock_file.read_text(encoding="ascii", errors="ignore").strip() != token_hash:
        raise RuntimeError("watcher launch lock does not match")
    stop_event = threading.Event()
    change_event = threading.Event()
    observer = None
    backend = "polling"
    counters = {"cycles": 0, "updated_files": 0, "removed_files": 0, "errors": 0}
    state = {
        "project": project,
        "db_path": str(db_path.expanduser().resolve()),
        "root": str(root.expanduser().resolve()),
        "pid": os.getpid(),
        "token_hash": token_hash,
        "state": "starting",
        "backend": backend,
        "interval_seconds": float(interval_seconds),
        "started_at": _now_iso(),
        "heartbeat_at": _now_iso(),
        "last_cycle_at": None,
        "last_error": None,
        **counters,
    }

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()
        change_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            database_path = db_path.expanduser().resolve()
            database_files = {
                database_path,
                Path(str(database_path) + "-shm"),
                Path(str(database_path) + "-wal"),
            }
            control_path = state_file.expanduser().resolve().parent

            def is_internal_event(raw_path: str | None) -> bool:
                if not raw_path:
                    return False
                candidate = Path(raw_path).expanduser().resolve()
                if candidate in database_files:
                    return True
                try:
                    candidate.relative_to(control_path)
                    return True
                except ValueError:
                    return False

            class Handler(FileSystemEventHandler):
                def on_any_event(self, event) -> None:
                    if event.is_directory:
                        return
                    paths = [getattr(event, "src_path", None), getattr(event, "dest_path", None)]
                    if any(path and not is_internal_event(path) for path in paths):
                        change_event.set()

            observer = Observer()
            observer.schedule(Handler(), str(root.expanduser().resolve()), recursive=True)
            observer.start()
            backend = "watchdog"
            state["backend"] = backend
        except (ImportError, OSError, RuntimeError):
            observer = None
        state["state"] = "running"
        _write_json(state_file, state)
        should_index = True
        while not stop_event.is_set() and not _stop_requested(stop_file):
            if should_index:
                try:
                    conn = connect(db_path)
                    try:
                        result = ingest_repo(conn, root, project=project)
                    finally:
                        conn.close()
                    counters["cycles"] += 1
                    counters["updated_files"] += int(result.get("updated_files", 0))
                    counters["removed_files"] += int(result.get("removed_files", 0))
                    state["last_cycle_at"] = _now_iso()
                    state["last_error"] = None
                except Exception as exc:
                    counters["errors"] += 1
                    state["last_error"] = f"{exc.__class__.__name__}: {exc}"
                state.update(counters)
            state["heartbeat_at"] = _now_iso()
            _write_json(state_file, state)
            if backend == "watchdog":
                changed = change_event.wait(timeout=max(0.1, min(float(interval_seconds), 5.0)))
                if changed:
                    time.sleep(min(0.25, float(interval_seconds)))
                    change_event.clear()
                should_index = changed
            else:
                stop_event.wait(timeout=float(interval_seconds))
                should_index = True
        state["state"] = "stopping"
        state["heartbeat_at"] = _now_iso()
        _write_json(state_file, state)
        return 0
    except Exception as exc:
        state["state"] = "error"
        state["last_error"] = f"{exc.__class__.__name__}: {exc}"
        state["heartbeat_at"] = _now_iso()
        _write_json(state_file, state)
        return 1
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)
        if state.get("state") != "error":
            state["state"] = "stopped"
            state["stopped_at"] = _now_iso()
            state["heartbeat_at"] = _now_iso()
            _write_json(state_file, state)
        if _is_safe_regular_file(stop_file):
            stop_file.unlink(missing_ok=True)
        try:
            if lock_file.read_text(encoding="ascii", errors="ignore").strip() == token_hash:
                lock_file.unlink(missing_ok=True)
        except OSError:
            pass
