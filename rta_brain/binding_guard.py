"""Cross-process guards for canonical project binding changes."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .runtime_control import is_safe_regular_file, prepare_control_dir, process_alive


_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()
_MAX_OWNER_BYTES = 4_096


def _paths(database: Path, project: str) -> dict[str, Path]:
    resolved = Path(database).expanduser().resolve()
    control = resolved.parent / ".rta-smriti-daemons"
    key = hashlib.sha256(f"{resolved}\0{project}".encode("utf-8")).hexdigest()[:20]
    return {
        "control": control,
        "gate": control / f"binding-{key}.gate",
        "leases": control / f"binding-{key}.leases",
    }


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_directory(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink() and not _is_reparse_point(path)
    except OSError:
        return False


def _read_owner(path: Path) -> dict:
    if not is_safe_regular_file(path):
        return {}
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return {}
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_size > _MAX_OWNER_BYTES:
            return {}
        raw = os.read(descriptor, _MAX_OWNER_BYTES + 1)
    except OSError:
        return {}
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_OWNER_BYTES:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _live_pid(payload: dict) -> bool:
    try:
        pid = int(payload.get("pid"))
    except (TypeError, ValueError):
        return False
    return pid > 0 and process_alive(pid)


def _remove_stale_gate(gate: Path) -> bool:
    owner_path = gate / "owner.json"
    owner = _read_owner(owner_path)
    try:
        owner_pid = int(owner.get("pid"))
    except (TypeError, ValueError):
        owner_pid = None
    if owner_pid != os.getpid() and _live_pid(owner):
        return False
    try:
        age = time.time() - gate.stat().st_mtime
    except OSError:
        return True
    if not owner and age < 5:
        return False
    if owner_path.exists() and not is_safe_regular_file(owner_path):
        raise ValueError("binding gate owner is linked or unsafe")
    owner_path.unlink(missing_ok=True)
    try:
        gate.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


@contextmanager
def _file_binding_gate(database: Path, project: str, *, timeout: float = 10.0):
    paths = _paths(database, project)
    prepare_control_dir(paths["control"], label="binding")
    gate = paths["gate"]
    deadline = time.monotonic() + max(0.1, float(timeout))
    token = uuid.uuid4().hex
    while True:
        try:
            gate.mkdir(mode=0o700)
            break
        except FileExistsError:
            if not _safe_directory(gate):
                raise ValueError("binding gate is linked or unsafe")
            if _remove_stale_gate(gate):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for the project binding gate")
            time.sleep(0.025)
    owner_path = gate / "owner.json"
    try:
        descriptor = os.open(owner_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump({"pid": os.getpid(), "token": token}, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        owner = _read_owner(owner_path)
        if owner.get("token") == token:
            for attempt in range(40):
                try:
                    owner_path.unlink(missing_ok=True)
                    gate.rmdir()
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    if attempt == 39:
                        raise
                    time.sleep(0.025)


@contextmanager
def binding_gate(database: Path, project: str, *, timeout: float = 10.0):
    gate = _paths(database, project)["gate"]
    key = os.path.normcase(str(gate))
    with _LOCAL_LOCKS_GUARD:
        local_lock = _LOCAL_LOCKS.setdefault(key, threading.Lock())
    if not local_lock.acquire(timeout=max(0.1, float(timeout))):
        raise TimeoutError("timed out waiting for the local project binding gate")
    try:
        with _file_binding_gate(database, project, timeout=timeout):
            yield
    finally:
        local_lock.release()


def _clean_leases(leases: Path) -> list[dict]:
    prepare_control_dir(leases, label="binding lease")
    active = []
    for path in leases.glob("*.json"):
        payload = _read_owner(path)
        if _live_pid(payload):
            active.append(payload)
            continue
        if path.exists() and not is_safe_regular_file(path):
            raise ValueError("binding lease is linked or unsafe")
        path.unlink(missing_ok=True)
    return active


class McpBindingLease:
    def __init__(self, database: Path, project: str):
        self.database = Path(database).expanduser().resolve()
        self.project = project
        self.path: Path | None = None
        self.token = uuid.uuid4().hex

    def __enter__(self):
        paths = _paths(self.database, self.project)
        with binding_gate(self.database, self.project):
            _clean_leases(paths["leases"])
            self.path = paths["leases"] / f"{os.getpid()}-{self.token}.json"
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump({"pid": os.getpid(), "token": self.token}, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if self.path is None:
            return
        with binding_gate(self.database, self.project):
            payload = _read_owner(self.path)
            if payload.get("token") == self.token:
                self.path.unlink(missing_ok=True)


@contextmanager
def rebind_guard(database: Path, project: str):
    paths = _paths(database, project)
    with binding_gate(database, project):
        active = _clean_leases(paths["leases"])
        if active:
            raise ValueError("stop the active MCP server before root rebind")
        yield
