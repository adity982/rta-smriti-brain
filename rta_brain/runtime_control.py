"""Hardened local process-control primitives shared by managed services."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def prepare_control_dir(path: Path, *, label: str = "runtime") -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or _is_reparse_point(path) or not path.is_dir():
        raise ValueError(f"{label} control directory is not a safe directory: {path}")
    if os.name != "nt":
        path.chmod(0o700)


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & 0x400)


def is_safe_regular_file(path: Path) -> bool:
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and not _is_reparse_point(path)
            and path.stat().st_nlink == 1
        )
    except OSError:
        return False


def write_json(path: Path, payload: dict, *, label: str = "runtime state") -> None:
    prepare_control_dir(path.parent, label=label.split()[0])
    if path.exists() and not is_safe_regular_file(path):
        raise ValueError(f"refusing linked {label}: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
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


def read_json(path: Path) -> dict | None:
    if not is_safe_regular_file(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_secret(path: Path, value: str, *, label: str = "runtime secret") -> None:
    prepare_control_dir(path.parent, label=label.split()[0])
    if path.exists() and not is_safe_regular_file(path):
        raise ValueError(f"refusing linked {label}: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def read_secret(path: Path, *, label: str = "runtime secret") -> str:
    if not is_safe_regular_file(path):
        raise ValueError(f"{label} is missing or linked: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"{label} is empty: {path}")
    return value


def write_stop_request(path: Path, *, label: str = "runtime") -> None:
    prepare_control_dir(path.parent, label=label)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if not is_safe_regular_file(path):
            raise ValueError(f"refusing linked {label} stop file: {path}")
        return
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
        stream.write("stop\n")


def stop_requested(path: Path, *, label: str = "runtime") -> bool:
    if not path.exists():
        return False
    if not is_safe_regular_file(path):
        raise ValueError(f"refusing linked {label} stop file: {path}")
    return True


def open_log(path: Path, *, label: str = "runtime"):
    prepare_control_dir(path.parent, label=label)
    if path.exists() and not is_safe_regular_file(path):
        raise ValueError(f"refusing linked {label} log: {path}")
    if path.exists() and path.stat().st_size > 2_097_152:
        rotated = path.with_suffix(path.suffix + ".1")
        if rotated.exists() and not is_safe_regular_file(rotated):
            raise ValueError(f"refusing linked rotated {label} log: {rotated}")
        rotated.unlink(missing_ok=True)
        os.replace(path, rotated)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    return os.fdopen(descriptor, "a", encoding="utf-8", buffering=1)


def process_alive(pid: int | None) -> bool:
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


def clear_control_files(paths: dict[str, Path], keys: Iterable[str]) -> None:
    for key in keys:
        path = paths[key]
        if is_safe_regular_file(path):
            path.unlink(missing_ok=True)


def detached_process_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": 0x00000008 | 0x00000200 | 0x08000000}
    return {"start_new_session": True}
