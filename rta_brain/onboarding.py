"""One-command, resumable project onboarding for Rta-Smriti."""

from __future__ import annotations

from pathlib import Path

from .db import connect
from .project import bootstrap_project, project_db_path, self_check, shell_cli_command, shell_quote
from .repository import repository_state
from .watch_daemon import start_watcher
from .continuity_daemon import DEFAULT_BACKLOG_TAIL_BYTES, start_continuity


SUPPORTED_TARGET_AGENTS = frozenset({
    "universal", "codex", "claude-code", "cursor", "github-copilot",
    "gemini-cli", "windsurf", "cline", "aider", "opencode", "continue", "custom",
})


def derive_project_name(root: Path) -> str:
    value = "".join(character.lower() if character.isalnum() else "-" for character in root.name)
    return value.strip("-") or "project"


def _stage(name: str, state: str, detail: str) -> dict:
    return {"name": name, "state": state, "detail": detail}


def _recovery_commands(tool_root: Path, repo: Path, brain_dir: Path, db_path: Path, project: str) -> dict:
    cli = shell_cli_command(tool_root)
    return {
        "resume": (
            f"{cli} start {shell_quote(repo)} --project {shell_quote(project)} "
            f"--brain-dir {shell_quote(brain_dir)} --no-open"
        ),
        "watcher": (
            f"{cli} --db {shell_quote(db_path)} watcher start {shell_quote(repo)} "
            f"--project {shell_quote(project)}"
        ),
        "console": f"{cli} console start --brain-dir {shell_quote(brain_dir)} --no-open",
        "verify": f"{cli} --db {shell_quote(db_path)} self-check --project {shell_quote(project)}",
    }


def onboard_project(
    tool_root: Path,
    path: Path,
    *,
    brain_dir: Path,
    project: str | None = None,
    target_agent: str = "universal",
    write_agents: bool = False,
    embedding_provider: str = "hash",
    watcher_interval: float = 2.0,
    sessions_root: Path | None = None,
    start_continuity_capture: bool = True,
    continuity_interval: float | None = None,
    continuity_inactivity: float = 900.0,
    continuity_lookback_days: float = 30.0,
    continuity_backlog_tail_bytes: int = DEFAULT_BACKLOG_TAIL_BYTES,
    port: int = 8765,
    open_browser: bool = True,
    start_sync: bool = True,
    manage_console: bool = True,
) -> dict:
    requested = path.expanduser().resolve()
    brains = brain_dir.expanduser().resolve()
    stages: list[dict] = []
    if not requested.is_dir():
        raise ValueError(f"project path does not exist or is not a directory: {requested}")
    if target_agent not in SUPPORTED_TARGET_AGENTS:
        raise ValueError(f"unsupported target agent: {target_agent}")

    git = repository_state(requested)
    repo = Path(git["repository_root"]).resolve() if git["is_git_repo"] else requested
    selected_project = project.strip() if project else derive_project_name(repo)
    if not selected_project:
        raise ValueError("project name cannot be empty")
    db_path = project_db_path(brains, selected_project)
    recovery = _recovery_commands(tool_root, repo, brains, db_path, selected_project)
    stages.append(_stage("discover", "complete", "Canonical project root and identity resolved."))

    result = {
        "status": "partial",
        "ready": False,
        "project": selected_project,
        "target_agent": target_agent,
        "repo_path": str(repo),
        "db_path": str(db_path),
        "git": git,
        "stages": stages,
        "recovery_commands": recovery,
    }
    try:
        bootstrap = bootstrap_project(
            None,
            repo,
            selected_project,
            brains,
            write_agents,
            tool_root,
            embedding_provider=embedding_provider,
        )
        result["bootstrap"] = bootstrap
        stages.append(_stage("bootstrap", "complete", "Brain migrated and repository index refreshed."))

        if start_sync:
            watcher = start_watcher(
                db_path,
                repo,
                selected_project,
                interval_seconds=watcher_interval,
            )
            if watcher.get("state") != "running":
                raise RuntimeError(f"repository watcher is not running: {watcher.get('state')}")
            stages.append(_stage("watcher", "complete", "Incremental repository sync is running."))
        else:
            watcher = {"status": "ok", "state": "disabled"}
            stages.append(_stage("watcher", "complete", "Incremental sync was explicitly disabled."))
        result["watcher"] = watcher

        if start_continuity_capture:
            sessions = (sessions_root or (Path.home() / ".codex" / "sessions")).expanduser().resolve()
            if sessions.is_dir():
                continuity = start_continuity(
                    db_path,
                    repo,
                    selected_project,
                    sessions,
                    interval_seconds=continuity_interval or max(0.1, watcher_interval),
                    inactivity_seconds=continuity_inactivity,
                    lookback_days=continuity_lookback_days,
                    backlog_tail_bytes=continuity_backlog_tail_bytes,
                )
                if continuity.get("state") != "running":
                    raise RuntimeError(f"task continuity capture is not running: {continuity.get('state')}")
                stages.append(_stage("continuity", "complete", "Managed Codex task continuity capture is running."))
            else:
                continuity = {
                    "status": "ok",
                    "state": "unavailable",
                    "reason": "codex_sessions_root_missing",
                    "sessions_root": str(sessions),
                }
                stages.append(_stage("continuity", "complete", "Codex task continuity capture skipped because the sessions directory was not found."))
        else:
            continuity = {"status": "ok", "state": "disabled"}
            stages.append(_stage("continuity", "complete", "Task continuity capture was explicitly disabled."))
        result["continuity"] = continuity

        if manage_console:
            from .console_daemon import start_console

            console = start_console(
                tool_root,
                brains,
                default_db=db_path,
                default_project=selected_project,
                port=port,
                open_browser=open_browser,
            )
            if console.get("state") != "running":
                raise RuntimeError(f"operator console is not running: {console.get('state')}")
        else:
            console = {"status": "ok", "state": "current"}
        result["console"] = console
        stages.append(_stage(
            "console", "complete",
            "Managed operator console is authenticated and reachable."
            if manage_console else "Current authenticated operator console remains active.",
        ))

        conn = connect(db_path)
        try:
            readiness = self_check(conn, project=selected_project, check_files=False)
        finally:
            conn.close()
        result["readiness"] = readiness
        if not readiness.get("ready"):
            raise RuntimeError("project brain did not pass readiness verification")
        stages.append(_stage("verify", "complete", "Indexed evidence and local runtime passed readiness checks."))
        result.update({"status": "ok", "ready": True})
        return result
    except Exception as exc:
        completed = {stage["name"] for stage in stages}
        failed_stage = next(
            name for name in ("bootstrap", "watcher", "console", "verify") if name not in completed
        )
        stages.append(_stage(failed_stage, "failed", f"{exc.__class__.__name__}: {exc}"))
        result["error"] = {"type": exc.__class__.__name__, "message": str(exc), "stage": failed_stage}
        return result
