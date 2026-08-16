"""Reversible, user-level login startup for the managed console."""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from .runtime_control import is_safe_regular_file


def _key(brain_dir: Path) -> str:
    canonical = str(brain_dir.expanduser().resolve())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _platform_support(platform_name: str, environment: dict[str, str]) -> tuple[str | None, str | None]:
    if platform_name == "win32":
        return "windows", None
    if platform_name == "darwin":
        return "macos", None
    if platform_name.startswith("linux"):
        if environment.get("WSL_DISTRO_NAME") or environment.get("WSL_INTEROP"):
            return None, "wsl"
        if not any(environment.get(name) for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP")):
            return None, "headless-linux"
        return "linux-desktop", None
    return None, "unsupported-platform"


def _entry_path(
    brain_dir: Path,
    *,
    platform_name: str,
    home: Path,
    environment: dict[str, str],
) -> tuple[Path | None, str | None, str | None]:
    kind, reason = _platform_support(platform_name, environment)
    if not kind:
        return None, None, reason
    suffix = _key(brain_dir)
    if kind == "windows":
        appdata = Path(environment.get("APPDATA") or home / "AppData" / "Roaming")
        path = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"Rta-Smriti-{suffix}.cmd"
    elif kind == "macos":
        path = home / "Library" / "LaunchAgents" / f"io.rta-smriti.console.{suffix}.plist"
    else:
        config = Path(environment.get("XDG_CONFIG_HOME") or home / ".config")
        path = config / "autostart" / f"rta-smriti-{suffix}.desktop"
    return path, kind, None


def _launch_parts(tool_root: Path, brain_dir: Path) -> list[str]:
    suffix = ["console", "start", "--brain-dir", str(brain_dir.expanduser().resolve()), "--no-open"]
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), *suffix]
    source_cli = tool_root.resolve() / "rta-brain.py"
    if source_cli.is_file():
        return [str(Path(sys.executable).resolve()), str(source_cli), *suffix]
    return [str(Path(sys.executable).resolve()), "-m", "rta_brain.cli", *suffix]


def _desktop_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`") + '"'


def _entry_text(kind: str, parts: list[str], key: str) -> str:
    if kind == "windows":
        return "@echo off\n" + subprocess.list2cmdline(parts) + "\n"
    if kind == "macos":
        arguments = "\n".join(f"      <string>{escape(part)}</string>" for part in parts)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>io.rta-smriti.console.{key}</string>
    <key>ProgramArguments</key>
    <array>
{arguments}
    </array>
    <key>RunAtLoad</key>
    <true/>
  </dict>
</plist>
"""
    command = " ".join(_desktop_quote(part) for part in parts)
    return f"""[Desktop Entry]
Type=Application
Name=Rta-Smriti Brain
Comment=Start the local operator console
Exec={command}
Terminal=false
X-GNOME-Autostart-enabled=true
"""


def _write_entry(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not is_safe_regular_file(path):
        raise ValueError(f"refusing linked autostart entry: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def autostart_status(
    brain_dir: Path,
    *,
    platform_name: str | None = None,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> dict:
    selected_platform = platform_name or sys.platform
    selected_home = (home or Path.home()).expanduser().resolve()
    selected_environment = dict(os.environ if environment is None else environment)
    entry, kind, reason = _entry_path(
        brain_dir,
        platform_name=selected_platform,
        home=selected_home,
        environment=selected_environment,
    )
    if entry is None:
        return {
            "status": "ok", "supported": False, "enabled": False,
            "platform": selected_platform, "reason": reason, "entry_path": None,
        }
    enabled = is_safe_regular_file(entry)
    unsafe = entry.exists() and not enabled
    return {
        "status": "ok", "supported": True, "enabled": enabled,
        "platform": kind, "reason": "unsafe-entry" if unsafe else None,
        "entry_path": str(entry),
    }


def enable_autostart(
    tool_root: Path,
    brain_dir: Path,
    *,
    platform_name: str | None = None,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> dict:
    selected_platform = platform_name or sys.platform
    selected_home = (home or Path.home()).expanduser().resolve()
    selected_environment = dict(os.environ if environment is None else environment)
    entry, kind, reason = _entry_path(
        brain_dir,
        platform_name=selected_platform,
        home=selected_home,
        environment=selected_environment,
    )
    if entry is None:
        return {
            "status": "unsupported", "supported": False, "enabled": False,
            "platform": selected_platform, "reason": reason, "entry_path": None,
        }
    parts = _launch_parts(tool_root, brain_dir)
    _write_entry(entry, _entry_text(kind, parts, _key(brain_dir)))
    return {
        "status": "ok", "supported": True, "enabled": True,
        "platform": kind, "reason": None, "entry_path": str(entry),
    }


def disable_autostart(
    brain_dir: Path,
    *,
    platform_name: str | None = None,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> dict:
    status = autostart_status(
        brain_dir, platform_name=platform_name, home=home, environment=environment,
    )
    entry_value = status.get("entry_path")
    if not entry_value:
        return status
    entry = Path(entry_value)
    if entry.exists() and not is_safe_regular_file(entry):
        raise ValueError(f"refusing linked autostart entry: {entry}")
    entry.unlink(missing_ok=True)
    return {**status, "enabled": False, "reason": None}
