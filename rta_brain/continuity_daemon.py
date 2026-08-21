"""Managed capture of local Codex session events for one canonical project."""

from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .continuity import ingest_codex_session, init_continuity_schema
from .db import ensure_project, now_iso, save_checkpoint
from .db import connect
from .watch_daemon import (
    _SPAWNED_PROCESSES,
    _clear_stale_control,
    _is_safe_regular_file,
    _open_log,
    _prepare_control_dir,
    _process_alive,
    _read_json,
    _stop_requested,
    _write_json,
    _write_stop_request,
)


MAX_SESSION_META_BYTES = 256_000
DEFAULT_BACKLOG_TAIL_BYTES = 2_000_000


def continuity_paths(db_path: Path, project: str) -> dict[str, Path]:
    database = db_path.expanduser().resolve()
    key = hashlib.sha256(f"continuity\0{database}\0{project}".encode("utf-8")).hexdigest()[:12]
    directory = database.parent / ".rta-smriti-daemons"
    stem = f"{database.stem}-continuity-{key}"
    return {
        "directory": directory,
        "state": directory / f"{stem}.json",
        "stop": directory / f"{stem}.stop",
        "lock": directory / f"{stem}.lock",
        "log": directory / f"{stem}.log",
    }


def continuity_status(db_path: Path, project: str) -> dict:
    payload = _read_json(continuity_paths(db_path, project)["state"])
    if not payload:
        return {"status": "ok", "state": "stopped", "project": project, "db_path": str(db_path.expanduser().resolve())}
    state = str(payload.get("state") or "unknown")
    if state in {"starting", "running", "stopping"}:
        heartbeat_fresh = False
        try:
            heartbeat = datetime.fromisoformat(str(payload.get("heartbeat_at")))
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
            heartbeat_fresh = age <= max(15.0, float(payload.get("interval_seconds", 2.0)) * 4)
        except (TypeError, ValueError):
            heartbeat_fresh = False
        process_alive = _process_alive(payload.get("pid"))
        payload["process_alive"] = process_alive
        if not process_alive or not heartbeat_fresh:
            state = "stale"
    if payload.get("root") and payload.get("sessions_root"):
        payload["binding_diagnostics"] = continuity_binding_diagnostics(
            Path(str(payload["sessions_root"])), Path(str(payload["root"])),
            lookback_days=float(payload.get("lookback_days", 30) or 30),
        )
    return {"status": "ok", **payload, "state": state}


def _worker_command(
    db_path: Path,
    project_root: Path,
    project: str,
    sessions_root: Path,
    paths: dict[str, Path],
    interval: float,
    inactivity: float,
    lookback_days: float,
    backlog_tail_bytes: int,
) -> list[str]:
    suffix = [
        "_continuity-worker", "--root", str(project_root), "--project", project,
        "--sessions-root", str(sessions_root), "--state-file", str(paths["state"]),
        "--stop-file", str(paths["stop"]), "--lock-file", str(paths["lock"]),
        "--interval", str(interval), "--inactivity", str(inactivity),
        "--lookback-days", str(lookback_days),
        "--backlog-tail-bytes", str(backlog_tail_bytes),
    ]
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--db", str(db_path), *suffix]
    return [str(Path(sys.executable).resolve()), "-m", "rta_brain.cli", "--db", str(db_path), *suffix]


def start_continuity(
    db_path: Path,
    project_root: Path,
    project: str,
    sessions_root: Path | None = None,
    *,
    interval_seconds: float = 5.0,
    inactivity_seconds: float = 900,
    lookback_days: float = 30,
    backlog_tail_bytes: int = DEFAULT_BACKLOG_TAIL_BYTES,
    startup_timeout: float = 10.0,
) -> dict:
    database = db_path.expanduser().resolve()
    root = project_root.expanduser().resolve()
    sessions = (sessions_root or (Path.home() / ".codex" / "sessions")).expanduser().resolve()
    interval = float(interval_seconds)
    inactivity = float(inactivity_seconds)
    lookback = float(lookback_days)
    tail_bytes = int(backlog_tail_bytes)
    if not database.is_file() or database.is_symlink() or database.stat().st_nlink > 1:
        raise ValueError(f"brain database must be an existing unlinked file: {database}")
    if not root.is_dir():
        raise ValueError(f"canonical project root does not exist: {root}")
    if not sessions.is_dir():
        raise ValueError(f"Codex sessions root does not exist: {sessions}")
    if not 0.1 <= interval <= 3600:
        raise ValueError("capture interval must be between 0.1 and 3,600 seconds")
    if not 1 <= inactivity <= 604800:
        raise ValueError("inactivity threshold must be between 1 second and 7 days")
    if not 0 <= lookback <= 36500:
        raise ValueError("lookback must be between 0 and 36,500 days; use 0 for all history")
    if not 64_000 <= tail_bytes <= 100_000_000:
        raise ValueError("session backlog tail must be between 64 KB and 100 MB")
    paths = continuity_paths(database, project)
    _prepare_control_dir(paths["directory"])
    current = continuity_status(database, project)
    if current["state"] in {"starting", "running", "stopping"}:
        return current
    if current["state"] == "stale" and current.get("process_alive"):
        raise RuntimeError("existing continuity process is alive but unresponsive; stop it before restarting")
    _clear_stale_control(paths)
    token = uuid.uuid4().hex
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    descriptor = os.open(paths["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
        stream.write(token_hash + "\n")
    env = {**os.environ, "RTA_SMIRTI_CONTINUITY_TOKEN": token}
    creationflags = 0
    kwargs = {"start_new_session": True}
    if os.name == "nt":
        creationflags = 0x00000008 | 0x00000200 | 0x08000000
        kwargs = {}
    log_stream = _open_log(paths["log"])
    try:
        process = subprocess.Popen(
            _worker_command(database, root, project, sessions, paths, interval, inactivity, lookback, tail_bytes),
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            stdout=log_stream, stderr=log_stream, close_fds=True, env=env,
            creationflags=creationflags, **kwargs,
        )
    except Exception:
        paths["lock"].unlink(missing_ok=True)
        raise
    finally:
        log_stream.close()
    deadline = time.monotonic() + max(1.0, float(startup_timeout))
    while time.monotonic() < deadline:
        state = continuity_status(database, project)
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
    raise RuntimeError(f"continuity service did not become ready within {startup_timeout:g} seconds")


def stop_continuity(db_path: Path, project: str, timeout: float = 10.0) -> dict:
    paths = continuity_paths(db_path, project)
    state = continuity_status(db_path, project)
    if state["state"] in {"stopped", "error"} or (state["state"] == "stale" and not state.get("process_alive")):
        _clear_stale_control(paths)
        return {**state, "state": "stopped"}
    _write_stop_request(paths["stop"])
    deadline = time.monotonic() + max(0.1, float(timeout))
    while time.monotonic() < deadline:
        state = continuity_status(db_path, project)
        if state["state"] == "stopped" or (
            state["state"] in {"stale", "error"} and not state.get("process_alive")
        ):
            process = _SPAWNED_PROCESSES.pop(str(paths["state"]), None)
            if process is not None:
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            return {**state, "state": "stopped"}
        time.sleep(0.05)
    raise TimeoutError(f"continuity service did not stop within {timeout:g} seconds")


def _session_identity(path: Path) -> tuple[str, Path] | None:
    try:
        with path.open("rb") as stream:
            consumed = 0
            while consumed < MAX_SESSION_META_BYTES:
                remaining = MAX_SESSION_META_BYTES - consumed
                raw = stream.readline(remaining + 1)
                if not raw:
                    return None
                if len(raw) > remaining:
                    return None
                consumed += len(raw)
                try:
                    row = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if row.get("type") != "session_meta" or not isinstance(row.get("payload"), dict):
                    continue
                payload = row["payload"]
                session_id = str(payload.get("id") or path.stem).strip()
                cwd = payload.get("cwd")
                if not session_id or not cwd:
                    return None
                return session_id, Path(str(cwd)).expanduser().resolve()
    except OSError:
        return None
    return None


def validate_codex_session_binding(path: Path, sessions_root: Path, project_root: Path) -> str:
    candidate = path.expanduser()
    sessions = sessions_root.expanduser().resolve()
    root = project_root.expanduser().resolve()
    if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_nlink > 1:
        raise ValueError("Codex session must be an existing unlinked file")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(sessions)
    except ValueError as exc:
        raise ValueError("Codex session is outside the configured session directory") from exc
    identity = _session_identity(resolved)
    if identity is None:
        raise ValueError("Codex session has no valid session metadata")
    session_id, cwd = identity
    try:
        cwd.relative_to(root)
    except ValueError as exc:
        raise ValueError("Codex session is not bound to the canonical project root") from exc
    return session_id


def _recent_session_candidates(
    sessions_root: Path,
    *,
    lookback_days: float = 30,
    now: float | None = None,
) -> list[Path]:
    sessions = sessions_root.expanduser().resolve()
    if not sessions.is_dir():
        return []
    current_time = time.time() if now is None else float(now)
    cutoff = None if float(lookback_days) == 0 else current_time - float(lookback_days) * 86400
    if cutoff is None:
        candidates = sessions.rglob("*.jsonl")
    else:
        candidate_set = set(sessions.glob("*.jsonl"))
        current_day = datetime.fromtimestamp(current_time, timezone.utc).date()
        for offset in range(int(float(lookback_days)) + 2):
            day = current_day - timedelta(days=offset)
            candidate_set.update((sessions / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}").rglob("*.jsonl"))
        candidates = sorted(candidate_set)
    bounded = []
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        if cutoff is not None and path.stat().st_mtime < cutoff:
            continue
        bounded.append(path)
    return bounded


def continuity_binding_diagnostics(
    sessions_root: Path,
    project_root: Path,
    *,
    lookback_days: float = 30,
    now: float | None = None,
) -> dict:
    """Explain Codex session discovery without exposing foreign working paths."""
    sessions = sessions_root.expanduser().resolve()
    root = project_root.expanduser().resolve()
    if not sessions.is_dir():
        return {
            "status": "ok", "sessions_root_present": False, "project_root_present": root.is_dir(),
            "recent_sessions": 0, "matching_sessions": 0, "foreign_sessions": 0,
            "invalid_sessions": 0, "hint": "Codex sessions directory was not found.",
        }
    if not root.is_dir():
        return {
            "status": "ok", "sessions_root_present": True, "project_root_present": False,
            "recent_sessions": 0, "matching_sessions": 0, "foreign_sessions": 0,
            "invalid_sessions": 0, "hint": "Canonical project root was not found.",
        }
    recent = matching = foreign = invalid = 0
    for path in _recent_session_candidates(sessions, lookback_days=lookback_days, now=now):
        identity = _session_identity(path)
        if identity is None:
            invalid += 1
            continue
        recent += 1
        _, cwd = identity
        try:
            cwd.relative_to(root)
        except ValueError:
            foreign += 1
        else:
            matching += 1
    hint = "Codex continuity can capture sessions for this canonical project root."
    if recent == 0:
        hint = "No recent Codex session metadata was found in the configured sessions directory."
    elif matching == 0 and foreign:
        hint = (
            "Recent Codex sessions exist, but their working directories are outside the canonical project root. "
            "Start the Codex task from this repository root or explicitly ingest the intended transcript."
        )
    elif invalid and matching == 0:
        hint = "Recent session files were found, but none had usable session metadata for this project."
    return {
        "status": "ok", "sessions_root_present": True, "project_root_present": True,
        "recent_sessions": recent, "matching_sessions": matching,
        "foreign_sessions": foreign, "invalid_sessions": invalid,
        "hint": hint,
    }


def discover_codex_sessions(
    sessions_root: Path,
    project_root: Path,
    *,
    lookback_days: float = 30,
    now: float | None = None,
) -> list[dict[str, str]]:
    """Return only sessions whose declared cwd is inside the canonical project root."""
    sessions_root = sessions_root.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if not sessions_root.is_dir() or not project_root.is_dir():
        return []
    found = []
    for path in _recent_session_candidates(sessions_root, lookback_days=lookback_days, now=now):
        identity = _session_identity(path)
        if identity is None:
            continue
        session_id, cwd = identity
        try:
            cwd.relative_to(project_root)
        except ValueError:
            continue
        found.append({"session_id": session_id, "path": str(path.resolve()), "cwd": str(cwd)})
    return sorted(found, key=lambda item: (item["session_id"], item["path"]))


def _text_content(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (_text_content(item) for item in value))).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            if key in value:
                text = _text_content(value[key])
                if text:
                    return text
    return ""


def _is_codex_control_message(text: str) -> bool:
    normalized = text.strip()
    return bool(re.fullmatch(r"<turn_aborted>.*?</turn_aborted>", normalized, flags=re.DOTALL))


def _checkpoint_for_session(
    conn,
    project: str,
    session_id: str,
    *,
    inactive: bool = False,
    trigger_override: str | None = None,
) -> dict | None:
    init_continuity_schema(conn)
    project_id = ensure_project(conn, project)
    rows = conn.execute(
        "SELECT id, event_type, payload_json FROM session_events WHERE project_id = ? AND session_id = ? ORDER BY id",
        (project_id, session_id),
    ).fetchall()
    if not rows:
        return None
    terminal = (rows[-1], trigger_override) if trigger_override else None
    if terminal is None:
        for row in reversed(rows):
            payload = json.loads(row["payload_json"])
            if row["event_type"] == "agent_event" and payload.get("type") in {"task_complete", "task_cancelled", "task_failed", "turn_aborted"}:
                terminal = (row, str(payload.get("type")))
                break
    if terminal is None and inactive:
        terminal = (rows[-1], "inactivity")
    if terminal is None:
        return None
    event, trigger = terminal
    marked = conn.execute(
        "SELECT 1 FROM continuity_checkpoint_marks WHERE project_id = ? AND session_id = ? AND event_id = ?",
        (project_id, session_id, int(event["id"])),
    ).fetchone()
    if marked:
        if inactive and int(rows[-1]["id"]) > int(event["id"]):
            event, trigger = rows[-1], "inactivity"
            marked = conn.execute(
                "SELECT 1 FROM continuity_checkpoint_marks WHERE project_id = ? AND session_id = ? AND event_id = ?",
                (project_id, session_id, int(event["id"])),
            ).fetchone()
        if marked:
            return None
    objective = "Continue captured Codex session"
    for row in reversed(rows):
        if row["event_type"] != "message":
            continue
        payload = json.loads(row["payload_json"])
        if payload.get("role") == "user":
            candidate = _text_content(payload.get("content"))[:4_000]
            if candidate and not _is_codex_control_message(candidate):
                objective = candidate
                break
    truncated = conn.execute(
        "SELECT 1 FROM session_events WHERE project_id = ? AND session_id = ? AND event_type = 'history_truncated' LIMIT 1",
        (project_id, session_id),
    ).fetchone()
    gap = "Automatically captured session state is unverified; review tool outcomes and source evidence before relying on it."
    if truncated:
        gap += " Earlier transcript history was intentionally truncated during bounded recovery and requires explicit operator acknowledgement."
    try:
        result = save_checkpoint(
            conn,
            project,
            objective,
            verified_evidence="",
            remaining_gaps=gap,
            next_action="Review the captured session events, reconcile work state, and continue from verified evidence.",
            prohibited_repetition="",
            source="continuity-daemon",
            trigger=trigger,
            session_id=session_id,
            _commit=False,
        )
        checkpoint_id = int(result["checkpoint"]["id"])
        conn.execute(
            "INSERT INTO continuity_checkpoint_marks(project_id, session_id, event_id, checkpoint_id, trigger, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, session_id, int(event["id"]), checkpoint_id, trigger, now_iso()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return result


def capture_cycle(
    conn,
    sessions_root: Path,
    project_root: Path,
    project: str,
    *,
    inactivity_seconds: float = 900,
    now: float | None = None,
    checkpoint_trigger: str | None = None,
    max_events_per_session: int = 250,
    max_sessions_per_cycle: int = 8,
    lookback_days: float = 30,
    backlog_tail_bytes: int = DEFAULT_BACKLOG_TAIL_BYTES,
) -> dict:
    init_continuity_schema(conn)
    current_time = time.time() if now is None else float(now)
    sessions = discover_codex_sessions(
        sessions_root, project_root, lookback_days=lookback_days, now=current_time,
    )
    latest_path = None
    if sessions:
        latest_path = max(sessions, key=lambda item: Path(item["path"]).stat().st_mtime_ns)["path"]
    project_id = ensure_project(conn, project)
    pending = []
    for item in sessions:
        row = conn.execute(
            "SELECT cursor FROM adapter_cursors WHERE project_id = ? AND adapter = 'codex-jsonl' AND stream_id = ?",
            (project_id, item["session_id"]),
        ).fetchone()
        if row is None or int(row["cursor"]) < Path(item["path"]).stat().st_size:
            pending.append(item)
    pending.sort(key=lambda item: Path(item["path"]).stat().st_mtime_ns, reverse=True)
    selected = pending[:max(1, int(max_sessions_per_cycle))]
    if latest_path and all(item["path"] != latest_path for item in selected):
        selected.append(next(item for item in sessions if item["path"] == latest_path))
    inserted = 0
    checkpoints = 0
    errors = []
    for item in selected:
        path = Path(item["path"])
        try:
            result = ingest_codex_session(
                conn, path, project, session_id=item["session_id"],
                max_events=max_events_per_session,
                backlog_tail_bytes=backlog_tail_bytes,
                expected_project_root=project_root,
                expected_sessions_root=sessions_root,
            )
            inserted += int(result["inserted"])
            is_latest = item["path"] == latest_path
            inactive = is_latest and current_time - path.stat().st_mtime >= max(1.0, float(inactivity_seconds))
            if is_latest and result["complete"]:
                checkpoints += int(
                    _checkpoint_for_session(
                        conn, project, item["session_id"], inactive=inactive,
                        trigger_override=checkpoint_trigger,
                    ) is not None
                )
        except Exception as exc:
            conn.rollback()
            errors.append({"session_id": item["session_id"], "type": exc.__class__.__name__, "message": str(exc)})
    return {
        "status": "ok" if not errors else "degraded",
        "project": project,
        "sessions_discovered": len(sessions),
        "sessions_pending": len(pending),
        "events_inserted": inserted,
        "checkpoints_created": checkpoints,
        "errors": errors,
    }


def run_continuity_worker(
    db_path: Path,
    project_root: Path,
    project: str,
    sessions_root: Path,
    state_file: Path,
    stop_file: Path,
    lock_file: Path,
    interval_seconds: float,
    inactivity_seconds: float,
    lookback_days: float,
    backlog_tail_bytes: int,
) -> int:
    token = os.environ.get("RTA_SMIRTI_CONTINUITY_TOKEN", "")
    if not token:
        raise RuntimeError("continuity launch token is missing")
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    if not lock_file.is_file() or lock_file.read_text(encoding="ascii", errors="ignore").strip() != token_hash:
        raise RuntimeError("continuity launch lock does not match")
    stop_event = threading.Event()
    counters = {"cycles": 0, "sessions_discovered": 0, "sessions_pending": 0, "events_inserted": 0, "checkpoints_created": 0, "errors": 0, "consecutive_errors": 0}
    state = {
        "project": project,
        "db_path": str(db_path.expanduser().resolve()),
        "root": str(project_root.expanduser().resolve()),
        "sessions_root": str(sessions_root.expanduser().resolve()),
        "pid": os.getpid(),
        "token_hash": token_hash,
        "state": "starting",
        "backend": "polling",
        "interval_seconds": float(interval_seconds),
        "inactivity_seconds": float(inactivity_seconds),
        "lookback_days": float(lookback_days),
        "backlog_tail_bytes": int(backlog_tail_bytes),
        "started_at": now_iso(),
        "heartbeat_at": now_iso(),
        "last_cycle_at": None,
        "last_capture_at": None,
        "last_checkpoint_at": None,
        "last_error": None,
        **counters,
    }

    def request_stop(_signum=None, _frame=None) -> None:
        stop_event.set()

    heartbeat_stop = threading.Event()
    state_write_lock = threading.Lock()

    def persist_state() -> None:
        with state_write_lock:
            state["heartbeat_at"] = now_iso()
            _write_json(state_file, dict(state))

    def heartbeat_loop() -> None:
        cadence = max(1.0, min(5.0, float(interval_seconds)))
        while not heartbeat_stop.wait(cadence):
            persist_state()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        state["state"] = "running"
        persist_state()
        heartbeat_thread = threading.Thread(target=heartbeat_loop, name="rta-continuity-heartbeat", daemon=True)
        heartbeat_thread.start()
        while not stop_event.is_set() and not _stop_requested(stop_file):
            try:
                conn = connect(db_path)
                try:
                    result = capture_cycle(
                        conn, sessions_root, project_root, project,
                        inactivity_seconds=inactivity_seconds,
                        lookback_days=lookback_days,
                        backlog_tail_bytes=backlog_tail_bytes,
                    )
                finally:
                    conn.close()
                counters["cycles"] += 1
                counters["sessions_discovered"] = int(result["sessions_discovered"])
                counters["sessions_pending"] = int(result["sessions_pending"])
                counters["events_inserted"] += int(result["events_inserted"])
                counters["checkpoints_created"] += int(result["checkpoints_created"])
                counters["errors"] += len(result["errors"])
                counters["consecutive_errors"] = counters["consecutive_errors"] + 1 if result["errors"] else 0
                state["last_cycle_at"] = now_iso()
                if result["events_inserted"]:
                    state["last_capture_at"] = state["last_cycle_at"]
                if result["checkpoints_created"]:
                    state["last_checkpoint_at"] = state["last_cycle_at"]
                state["last_error"] = result["errors"][-1]["message"] if result["errors"] else None
            except Exception as exc:
                counters["errors"] += 1
                counters["consecutive_errors"] += 1
                state["last_error"] = f"{exc.__class__.__name__}: {exc}"
            state.update(counters)
            persist_state()
            stop_event.wait(timeout=float(interval_seconds))
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=10)
        try:
            conn = connect(db_path)
            try:
                final_result = capture_cycle(
                    conn, sessions_root, project_root, project,
                    inactivity_seconds=inactivity_seconds,
                    checkpoint_trigger="service_shutdown",
                    lookback_days=lookback_days,
                    backlog_tail_bytes=backlog_tail_bytes,
                )
            finally:
                conn.close()
            counters["events_inserted"] += int(final_result["events_inserted"])
            counters["checkpoints_created"] += int(final_result["checkpoints_created"])
            counters["errors"] += len(final_result["errors"])
            if final_result["checkpoints_created"]:
                state["last_checkpoint_at"] = now_iso()
            state.update(counters)
        except Exception as exc:
            counters["errors"] += 1
            state["last_error"] = f"{exc.__class__.__name__}: {exc}"
            state.update(counters)
        state["state"] = "stopping"
        persist_state()
        return 0
    except Exception as exc:
        heartbeat_stop.set()
        state["state"] = "error"
        state["last_error"] = f"{exc.__class__.__name__}: {exc}"
        persist_state()
        return 1
    finally:
        heartbeat_stop.set()
        if state.get("state") != "error":
            state["state"] = "stopped"
            state["stopped_at"] = now_iso()
            persist_state()
        if _is_safe_regular_file(stop_file):
            stop_file.unlink(missing_ok=True)
        try:
            if lock_file.read_text(encoding="ascii", errors="ignore").strip() == token_hash:
                lock_file.unlink(missing_ok=True)
        except OSError:
            pass
