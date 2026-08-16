"""Minimal entry point for the detached repository-watcher process."""

from __future__ import annotations

import argparse
from pathlib import Path

from .watch_daemon import run_watcher_worker


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--lock-file", required=True)
    parser.add_argument("--interval", type=float, required=True)
    args = parser.parse_args(argv)
    return run_watcher_worker(
        Path(args.db),
        Path(args.root),
        args.project,
        Path(args.state_file),
        Path(args.stop_file),
        Path(args.lock_file),
        args.interval,
    )


if __name__ == "__main__":
    raise SystemExit(main())
