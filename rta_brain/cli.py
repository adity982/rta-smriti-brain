import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .autostart import autostart_status, disable_autostart, enable_autostart
from .context import build_context_pack, build_continuation_prompt
from .benchmark import (
    append_benchmark_history, benchmark_history, default_public_benchmark_path,
    run_public_benchmark, write_benchmark_report,
)
from .console import publish_readiness, run_dashboard
from .console_daemon import (
    console_status,
    open_console,
    restart_console,
    run_console_worker,
    start_console,
    stop_console,
)
from .continuity import (
    append_event, ingest_codex_session, list_events, operational_readiness,
    reconcile_work_items, upsert_work_item,
)
from .continuity_daemon import (
    continuity_status, run_continuity_worker, start_continuity, stop_continuity,
)
from .db import (
    connect, doctor, get_project_settings, graph, graph_query, ingest_repo, ingest_thread, init_project, reflect,
    integrity_diagnostics, project_binding_status, rebind_project_root, remember, save_checkpoint, search,
    stale_check, update_project_settings,
)
from .governance import build_operational_context, create_policy, list_policies, list_receipts, preflight, retire_policy
from .diagnostics import retrieval_diagnostics
from .hooks import install_git_hooks, uninstall_git_hooks
from .lifecycle import apply_memory_feedback, run_conservative_decay
from .onboarding import SUPPORTED_TARGET_AGENTS, onboard_project
from .portability import (
    export_bundle, import_bundle, inspect_bundle, snapshot_create, snapshot_create_encrypted,
    snapshot_keygen, snapshot_passphrase_keygen, snapshot_restore_encrypted, snapshot_verify,
    snapshot_verify_encrypted,
)
from .project import (
    bootstrap_project, install_local, mcp_config_payload, mcp_doctor,
    mcp_gateway_config_payload, projects_list, self_check,
)
from .watch import watch_repository
from .watch_daemon import run_watcher_worker, start_watcher, stop_watcher, watcher_status
from .workspaces import (
    add_project_to_workspace, create_workspace, delete_workspace, get_workspace, list_workspaces,
    remove_project_from_workspace, search_workspace, workspace_health,
)
from .temporal import (
    append_claim, attach_evidence, change_claim_state, define_validator,
    observe_repository_anchor, rebuild_projections, record_abstention,
    relate_claims, revise_claim, run_validator, truth_as_of, truth_at_commit,
    truth_current, truth_diff, truth_explain, truth_history, validator_history,
    verify_ledger,
)


def default_db_path() -> Path:
    return Path.cwd() / ".rta-smriti" / "brain.sqlite"


def tool_root() -> Path:
    return Path(__file__).resolve().parents[1]


def emit(payload, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif isinstance(payload, str):
        print(payload, end="" if payload.endswith("\n") else "\n")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def parse_json_argument(name: str, value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must contain valid JSON") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rta-brain", description="Rta-Smriti local project brain")
    parser.add_argument("--db", default=str(default_db_path()), help="Path to SQLite brain file")
    parser.add_argument("--json", action="store_true", help="Emit stable JSON")
    parser.add_argument("--version", action="version", version=f"rta-brain {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_options(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--db", default=argparse.SUPPRESS, help="Path to SQLite brain file")
        command_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit stable JSON")

    init = sub.add_parser("init", help="Initialize a project brain")
    add_common_options(init)
    init.add_argument("--project", default="default")
    init.add_argument("--root", default=str(Path.cwd()))
    init.add_argument("--rebind-root", action="store_true", help="Deprecated; use root-rebind so backup and rollback are enforced")

    remember_cmd = sub.add_parser("remember", help="Store a durable memory")
    add_common_options(remember_cmd)
    remember_cmd.add_argument("text")
    remember_cmd.add_argument("--project", default="default")
    remember_cmd.add_argument("--type", default="fact")
    remember_cmd.add_argument("--pramana", default="smriti", choices=["pratyaksha", "sabda", "anumana", "smriti", "kalpana"])
    remember_cmd.add_argument("--confidence", type=float, default=0.75)
    remember_cmd.add_argument("--priority", type=int, default=5)
    remember_cmd.add_argument("--source-path")
    remember_cmd.add_argument("--source-hash")
    remember_cmd.add_argument("--verification-command")
    remember_cmd.add_argument("--verification-status", choices=("unverified", "verified", "failed", "stale"), default="unverified")
    remember_cmd.add_argument("--verification-timestamp")

    ingest = sub.add_parser("ingest-repo", help="Index a repository or folder")
    add_common_options(ingest)
    ingest.add_argument("path")
    ingest.add_argument("--project", default="default")
    ingest.add_argument("--force", action="store_true", help="Re-read and re-index every eligible file even when metadata is unchanged")
    ingest.add_argument("--repair-deep-stale", action="store_true", help="Hash every eligible file and re-index only content-drifted sources")
    ingest.add_argument("--rebind-root", action="store_true", help="Deprecated; use root-rebind so backup and rollback are enforced")

    root_rebind = sub.add_parser("root-rebind", help="Back up and atomically migrate a project brain to another checkout")
    add_common_options(root_rebind)
    root_rebind.add_argument("path")
    root_rebind.add_argument("--project", default="default")
    root_rebind.add_argument("--backup", required=True, help="No-clobber SQLite backup written before migration")

    watch = sub.add_parser("watch-repo", help="Continuously refresh a repository using the incremental index")
    add_common_options(watch)
    watch.add_argument("path")
    watch.add_argument("--project", default="default")
    watch.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")

    watcher = sub.add_parser("watcher", help="Manage the background incremental repository watcher")
    add_common_options(watcher)
    watcher.add_argument("action", choices=("start", "status", "stop"))
    watcher.add_argument("path", nargs="?", help="Repository path; defaults to the project's bound root")
    watcher.add_argument("--project", default="default")
    watcher.add_argument("--interval", type=float, default=2.0, help="Event coalescing or polling interval in seconds")

    worker = sub.add_parser("_watch-worker", help=argparse.SUPPRESS)
    worker.add_argument("--root", required=True)
    worker.add_argument("--project", required=True)
    worker.add_argument("--state-file", required=True)
    worker.add_argument("--stop-file", required=True)
    worker.add_argument("--lock-file", required=True)
    worker.add_argument("--interval", type=float, required=True)

    continuity = sub.add_parser("continuity", help="Manage automatic Codex transcript capture and checkpoints")
    add_common_options(continuity)
    continuity.add_argument("action", choices=("start", "status", "stop"))
    continuity.add_argument("--project", default="default")
    continuity.add_argument("--root", help="Canonical project root; defaults to the bound root")
    continuity.add_argument("--sessions-root", default=str(Path.home() / ".codex" / "sessions"))
    continuity.add_argument("--interval", type=float, default=5.0)
    continuity.add_argument("--inactivity", type=float, default=900.0)
    continuity.add_argument("--lookback-days", type=float, default=30.0, help="Initial session lookback; 0 imports all history")
    continuity.add_argument("--backlog-tail-mb", type=float, default=2.0, help="Recent tail retained when a session backlog is oversized")

    continuity_worker = sub.add_parser("_continuity-worker", help=argparse.SUPPRESS)
    continuity_worker.add_argument("--root", required=True)
    continuity_worker.add_argument("--project", required=True)
    continuity_worker.add_argument("--sessions-root", required=True)
    continuity_worker.add_argument("--state-file", required=True)
    continuity_worker.add_argument("--stop-file", required=True)
    continuity_worker.add_argument("--lock-file", required=True)
    continuity_worker.add_argument("--interval", type=float, required=True)
    continuity_worker.add_argument("--inactivity", type=float, required=True)
    continuity_worker.add_argument("--lookback-days", type=float, required=True)
    continuity_worker.add_argument("--backlog-tail-bytes", type=int, required=True)

    settings = sub.add_parser("settings", help="Read or update a project's indexing and retrieval policy")
    add_common_options(settings)
    settings.add_argument("--project", default="default")
    settings.add_argument("--max-file-mb", type=float)
    settings.add_argument("--large-file-policy", choices=("metadata", "block"))
    settings.add_argument("--parser-adapter", choices=("auto", "regex", "tree-sitter", "lsp"))
    settings.add_argument("--lsp-command")
    settings.add_argument("--lsp-auto-discovery", action=argparse.BooleanOptionalAction, default=None)
    settings.add_argument("--embedding-provider", choices=("none", "hash", "sentence-transformers"))
    settings.add_argument("--embedding-model")
    settings.add_argument("--hybrid-weight", type=float)
    settings.add_argument("--compaction-provider", choices=("none", "ollama"))
    settings.add_argument("--compaction-model")
    settings.add_argument("--compaction-endpoint")
    settings.add_argument("--compaction-timeout", type=float)

    thread = sub.add_parser("ingest-thread", help="Index a long thread, transcript, JSONL session, or handoff file")
    add_common_options(thread)
    thread.add_argument("path")
    thread.add_argument("--project", default="default")
    thread.add_argument("--title")

    search_cmd = sub.add_parser("search", help="Search memories and indexed files")
    add_common_options(search_cmd)
    search_cmd.add_argument("query")
    search_cmd.add_argument("--project")
    search_cmd.add_argument("--limit", type=int, default=8)

    graph_cmd = sub.add_parser("graph", help="Read the local entity graph")
    add_common_options(graph_cmd)
    graph_cmd.add_argument("--project", default="default")
    graph_cmd.add_argument("--limit", type=int, default=100)

    graph_query_cmd = sub.add_parser("graph-query", help="Traverse dependencies, dependents, or impact around an entity")
    add_common_options(graph_query_cmd)
    graph_query_cmd.add_argument("target")
    graph_query_cmd.add_argument("--project", default="default")
    graph_query_cmd.add_argument("--type", dest="query_type", choices=("dependencies", "dependents", "impact", "evidence", "relevance"), default="impact")
    graph_query_cmd.add_argument("--depth", type=int, default=2)
    graph_query_cmd.add_argument("--limit", type=int, default=100)

    truth_cmd = sub.add_parser("truth", help="Read and write temporal project truth")
    add_common_options(truth_cmd)
    truth_actions = truth_cmd.add_subparsers(dest="truth_action", required=True)

    truth_assert = truth_actions.add_parser("assert", help="Append a new truth claim")
    truth_assert.add_argument("--project", default="default")
    truth_assert.add_argument("--root", required=True, help="Exact canonical project root")
    truth_assert.add_argument("--claim-id")
    truth_assert.add_argument("--subject", required=True)
    truth_assert.add_argument("--predicate", required=True)
    truth_assert.add_argument("--value-json", required=True)
    truth_assert.add_argument("--idempotency-key", required=True)
    truth_assert.add_argument("--expected-version", type=int, required=True)
    truth_assert.add_argument("--valid-from")
    truth_assert.add_argument("--valid-to")
    truth_assert.add_argument("--expires-at")
    truth_assert.add_argument(
        "--state",
        default="observed",
        choices=(
            "hypothesis", "observed", "corroborated", "accepted", "disputed",
            "stale", "refuted", "superseded", "retracted",
        ),
    )
    truth_assert.add_argument("--confidence", type=float, default=1.0)
    truth_assert.add_argument("--actor-type", choices=("operator", "agent"), default="operator")
    truth_assert.add_argument("--actor-id", default="local-operator")

    truth_current_cmd = truth_actions.add_parser("current", help="Read one current truth claim")
    truth_current_cmd.add_argument("--project", default="default")
    truth_current_cmd.add_argument("--claim-id", required=True)
    truth_current_cmd.add_argument("--valid-at")

    truth_state = truth_actions.add_parser("state", help="Append an epistemic state transition")
    truth_state.add_argument("--project", default="default")
    truth_state.add_argument("--root", required=True, help="Exact canonical project root")
    truth_state.add_argument("--claim-id", required=True)
    truth_state.add_argument(
        "--state", required=True,
        choices=(
            "hypothesis", "observed", "corroborated", "accepted", "disputed",
            "stale", "refuted", "superseded", "retracted",
        ),
    )
    truth_state.add_argument("--reason", required=True)
    truth_state.add_argument("--idempotency-key", required=True)
    truth_state.add_argument("--expected-version", type=int, required=True)
    truth_state.add_argument("--actor-type", choices=("operator", "agent"), default="operator")
    truth_state.add_argument("--actor-id", default="local-operator")

    truth_history_cmd = truth_actions.add_parser("history", help="Read recorded history for one claim")
    truth_history_cmd.add_argument("--project", default="default")
    truth_history_cmd.add_argument("--claim-id", required=True)
    truth_history_cmd.add_argument("--limit", type=int, default=500)

    truth_as_of_cmd = truth_actions.add_parser("as-of", help="Read valid-time truth at a recorded sequence")
    truth_as_of_cmd.add_argument("--project", default="default")
    truth_as_of_cmd.add_argument("--claim-id", required=True)
    truth_as_of_cmd.add_argument("--valid-at", required=True)
    truth_as_of_cmd.add_argument("--recorded-sequence", type=int, required=True)

    truth_revise = truth_actions.add_parser("revise", help="Append a corrected truth claim value")
    truth_revise.add_argument("--project", default="default")
    truth_revise.add_argument("--root", required=True)
    truth_revise.add_argument("--claim-id", required=True)
    truth_revise.add_argument("--value-json", required=True)
    truth_revise.add_argument("--reason", required=True)
    truth_revise.add_argument("--idempotency-key", required=True)
    truth_revise.add_argument("--expected-version", type=int, required=True)
    truth_revise.add_argument("--valid-from")
    truth_revise.add_argument("--valid-to")
    truth_revise.add_argument("--actor-type", choices=("operator", "agent"), default="operator")
    truth_revise.add_argument("--actor-id", default="local-operator")

    truth_relate = truth_actions.add_parser("relate", help="Append a typed relation between current claims")
    truth_relate.add_argument("--project", default="default")
    truth_relate.add_argument("--root", required=True)
    truth_relate.add_argument("--relation-id")
    truth_relate.add_argument("--from-claim", required=True)
    truth_relate.add_argument("--type", required=True, choices=(
        "supports", "contradicts", "supersedes", "retracts", "refutes",
        "derived_from", "alternate_of", "specialization_of",
    ))
    truth_relate.add_argument("--to-claim", required=True)
    truth_relate.add_argument("--idempotency-key", required=True)
    truth_relate.add_argument("--expected-version", type=int, required=True)
    truth_relate.add_argument("--confidence", type=float, default=0.7)
    truth_relate.add_argument("--actor-type", choices=("operator", "agent"), default="operator")
    truth_relate.add_argument("--actor-id", default="local-operator")

    truth_evidence = truth_actions.add_parser("evidence", help="Attach provenance-bearing evidence to a claim")
    truth_evidence.add_argument("--project", default="default")
    truth_evidence.add_argument("--root", required=True)
    truth_evidence.add_argument("--claim-id", required=True)
    truth_evidence.add_argument("--evidence-id", required=True)
    truth_evidence.add_argument("--source-identifier", required=True)
    truth_evidence.add_argument("--source-hash")
    truth_evidence.add_argument("--method", required=True)
    truth_evidence.add_argument("--polarity", required=True, choices=("supporting", "weakening", "refuting"))
    truth_evidence.add_argument("--authority-class", required=True)
    truth_evidence.add_argument("--confidence", type=float, required=True)
    truth_evidence.add_argument("--uncertainty", default="")
    truth_evidence.add_argument("--provenance-json", required=True)
    truth_evidence.add_argument("--idempotency-key", required=True)
    truth_evidence.add_argument("--expected-version", type=int, required=True)
    truth_evidence.add_argument("--verification-status", default="unverified", choices=("unverified", "verified", "failed", "stale"))
    truth_evidence.add_argument("--actor-type", choices=("operator", "agent"), default="operator")
    truth_evidence.add_argument("--actor-id", default="local-operator")

    truth_abstain = truth_actions.add_parser("abstain", help="Record an explicit evidence-bound abstention")
    truth_abstain.add_argument("--project", default="default")
    truth_abstain.add_argument("--root", required=True)
    truth_abstain.add_argument("--abstention-id")
    truth_abstain.add_argument("--query-scope", required=True)
    truth_abstain.add_argument("--missing-evidence-json", required=True)
    truth_abstain.add_argument("--unresolved-conflicts-json", required=True)
    truth_abstain.add_argument("--minimum-revalidation-action", required=True)
    truth_abstain.add_argument("--idempotency-key", required=True)
    truth_abstain.add_argument("--expected-version", type=int, required=True)
    truth_abstain.add_argument("--actor-type", choices=("operator", "agent"), default="operator")
    truth_abstain.add_argument("--actor-id", default="local-operator")

    truth_explain_cmd = truth_actions.add_parser("explain", help="Explain a claim with evidence and relations")
    truth_explain_cmd.add_argument("--project", default="default")
    truth_explain_cmd.add_argument("--claim-id", required=True)
    truth_explain_cmd.add_argument("--valid-at")

    truth_diff_cmd = truth_actions.add_parser("diff", help="Compare truth at two recorded sequences")
    truth_diff_cmd.add_argument("--project", default="default")
    truth_diff_cmd.add_argument("--from-sequence", type=int, required=True)
    truth_diff_cmd.add_argument("--to-sequence", type=int, required=True)
    truth_diff_cmd.add_argument("--valid-at", required=True)
    truth_diff_cmd.add_argument("--limit", type=int, default=500)

    truth_anchor = truth_actions.add_parser("anchor", help="Observe the exact current Git repository anchor")
    truth_anchor.add_argument("--project", default="default")
    truth_anchor.add_argument("--root", required=True)
    truth_anchor.add_argument("--anchor-id", required=True)
    truth_anchor.add_argument("--idempotency-key", required=True)
    truth_anchor.add_argument("--expected-version", type=int, required=True)

    truth_commit = truth_actions.add_parser("at-commit", help="Read truth at an explicitly observed Git commit")
    truth_commit.add_argument("--project", default="default")
    truth_commit.add_argument("--claim-id", required=True)
    truth_commit.add_argument("--commit", required=True)
    truth_commit.add_argument("--valid-at", required=True)

    truth_validator = truth_actions.add_parser("validator", help="Define, run, or inspect deterministic validators")
    validator_actions = truth_validator.add_subparsers(dest="validator_action", required=True)
    validator_add = validator_actions.add_parser("add", help="Define an inert validator policy")
    validator_add.add_argument("--project", default="default")
    validator_add.add_argument("--root", required=True)
    validator_add.add_argument("--validator-id", required=True)
    validator_add.add_argument("--type", required=True, choices=(
        "file_exists", "file_sha256", "json_pointer_equals", "sqlite_integrity",
        "git_head_equals", "git_clean_state", "command_exit",
    ))
    validator_add.add_argument("--claim-id", required=True)
    validator_add.add_argument("--config-json", required=True)
    validator_add.add_argument("--failure-effect", required=True, choices=("disputed", "stale", "refuted"))
    validator_add.add_argument("--idempotency-key", required=True)
    validator_add.add_argument("--expected-version", type=int, required=True)
    validator_add.add_argument("--actor-id", default="local-operator")
    validator_run = validator_actions.add_parser("run", help="Execute a registered deterministic validator")
    validator_run.add_argument("--project", default="default")
    validator_run.add_argument("--root", required=True)
    validator_run.add_argument("--validator-id", required=True)
    validator_run.add_argument("--idempotency-key", required=True)
    validator_run.add_argument("--expected-version", type=int, required=True)
    validator_run.add_argument("--allow-command", action="store_true")
    validator_run.add_argument("--trusted-executable", action="append", default=[])
    validator_run.add_argument("--actor-id", default="local-operator")
    validator_history_cmd = validator_actions.add_parser("history", help="Read bounded validator result history")
    validator_history_cmd.add_argument("--project", default="default")
    validator_history_cmd.add_argument("--validator-id", required=True)
    validator_history_cmd.add_argument("--limit", type=int, default=100)

    truth_ledger = truth_actions.add_parser("ledger", help="Verify the immutable event ledger")
    ledger_actions = truth_ledger.add_subparsers(dest="ledger_action", required=True)
    ledger_verify = ledger_actions.add_parser("verify")
    ledger_verify.add_argument("--project", default="default")

    truth_projection = truth_actions.add_parser("projection", help="Rebuild or compare temporal projections")
    projection_actions = truth_projection.add_subparsers(dest="projection_action", required=True)
    projection_rebuild = projection_actions.add_parser("rebuild")
    projection_rebuild.add_argument("--project", default="default")
    projection_rebuild.add_argument("--root", required=True)
    projection_compare = projection_actions.add_parser("compare")
    projection_compare.add_argument("--project", default="default")

    diagnostics_cmd = sub.add_parser("retrieval-diagnostics", help="Explain retrieval mode, coverage, ranking, evidence, and freshness")
    add_common_options(diagnostics_cmd)
    diagnostics_cmd.add_argument("query")
    diagnostics_cmd.add_argument("--project", default="default")
    diagnostics_cmd.add_argument("--limit", type=int, default=8)

    benchmark_cmd = sub.add_parser("benchmark", help="Run the reproducible public retrieval and safety benchmark")
    add_common_options(benchmark_cmd)
    benchmark_cmd.add_argument("--dataset", default=str(default_public_benchmark_path()))
    benchmark_cmd.add_argument("--include-semantic", action="store_true")
    benchmark_cmd.add_argument("--semantic-model", default="all-MiniLM-L6-v2")
    benchmark_cmd.add_argument("--report", help="Write a shareable Markdown benchmark report")
    benchmark_cmd.add_argument("--history", help="Append to a bounded local JSONL run history")
    benchmark_cmd.add_argument("--label", default="run", help="Short label stored with a benchmark history entry")

    workspace_cmd = sub.add_parser("workspace", help="Create and use a multi-project workspace")
    add_common_options(workspace_cmd)
    workspace_cmd.add_argument("action", choices=("create", "add", "remove", "delete", "show", "health", "list", "search"))
    workspace_cmd.add_argument("--name")
    workspace_cmd.add_argument("--description", default="")
    workspace_cmd.add_argument("--project")
    workspace_cmd.add_argument("--member-db", help="Brain database containing the member project")
    workspace_cmd.add_argument("--role", default="member")
    workspace_cmd.add_argument("--query")
    workspace_cmd.add_argument("--limit", type=int, default=4)

    bundle_export = sub.add_parser("bundle-export", help="Export selected memories, checkpoints, and policies with redaction")
    add_common_options(bundle_export)
    bundle_export.add_argument("output")
    bundle_export.add_argument("--project", action="append", dest="projects")
    bundle_export.add_argument("--include", action="append", choices=("memories", "checkpoints", "policies"))
    bundle_export.add_argument("--no-redact", action="store_true")
    bundle_export.add_argument("--preview", action="store_true", help="Inspect the proposed bundle without writing it")

    bundle_import = sub.add_parser("bundle-import", help="Verify and import a selective Rta-Smriti bundle")
    add_common_options(bundle_import)
    bundle_import.add_argument("source")
    bundle_import.add_argument("--conflict", choices=("rename", "merge", "fail"), default="rename")
    bundle_import.add_argument("--preview", action="store_true", help="Validate and report conflicts without changing the brain")

    snapshot_cmd = sub.add_parser("snapshot", help="Create, verify, encrypt, or restore a local brain snapshot")
    add_common_options(snapshot_cmd)
    snapshot_cmd.add_argument(
        "action",
        choices=("create", "verify", "keygen", "passphrase-keygen", "encrypt", "verify-encrypted", "restore"),
    )
    snapshot_cmd.add_argument("path")
    snapshot_cmd.add_argument("--key", help="Shared HMAC key path for compatible private snapshots")
    snapshot_cmd.add_argument("--private-key", help="Ed25519 private PEM key path for public-key snapshot creation")
    snapshot_cmd.add_argument("--public-key", help="Ed25519 public PEM key path for public-key snapshot verification")
    snapshot_cmd.add_argument("--passphrase", help="Local passphrase file for encrypted snapshot operations")
    snapshot_cmd.add_argument("--output-db", help="New database path for encrypted snapshot restore")

    hooks_cmd = sub.add_parser("git-hooks", help="Opt in or out of managed Git checkpoint hooks")
    add_common_options(hooks_cmd)
    hooks_cmd.add_argument("action", choices=("install", "uninstall"))
    hooks_cmd.add_argument("--root", default=str(Path.cwd()))
    hooks_cmd.add_argument("--project", default="default")

    feedback_cmd = sub.add_parser("memory-feedback", help="Record evidence-backed usefulness feedback for a memory")
    add_common_options(feedback_cmd)
    feedback_cmd.add_argument("memory_id", type=int)
    feedback_cmd.add_argument("--project", default="default")
    feedback_cmd.add_argument("--outcome", choices=("helpful", "neutral", "harmful"), required=True)
    feedback_cmd.add_argument("--evidence", default="")

    decay_cmd = sub.add_parser("memory-decay", help="Conservatively age unverified inference and hypothesis memories")
    add_common_options(decay_cmd)
    decay_cmd.add_argument("--project", default="default")
    decay_cmd.add_argument("--minimum-age-days", type=int, default=90)
    decay_cmd.add_argument("--step", type=float, default=0.03)

    pack = sub.add_parser("context-pack", help="Build a compact task context pack")
    add_common_options(pack)
    pack.add_argument("task")
    pack.add_argument("--project", default="default")
    pack.add_argument("--limit", type=int, default=8)
    pack.add_argument("--max-tokens", type=int, default=4000)

    stale = sub.add_parser("stale-check", help="Check whether indexed files changed")
    add_common_options(stale)
    stale.add_argument("--project", default="default")
    stale.add_argument("--deep", action="store_true", help="Hash file contents instead of using the fast stat manifest")
    stale.add_argument("--rehash", action="store_true", help="Bypass the stat-keyed hash cache; implies --deep")
    stale.add_argument("--details", action="store_true", help="Include fresh file rows as well as anomalies")
    stale.add_argument("--detail-limit", type=int, default=50, help="Maximum freshness detail rows to emit (0-500)")
    stale.add_argument("--root", help="Active checkout root; mismatches fail closed before freshness is claimed")

    integrity_cmd = sub.add_parser("integrity-diagnostics", help="Report schema, binding, and duplicate-root integrity without local paths")
    add_common_options(integrity_cmd)
    integrity_cmd.add_argument("--project", default="default")
    integrity_cmd.add_argument("--root", help="Active checkout root to verify against the stored binding")

    checkpoint = sub.add_parser("checkpoint", help="Save a structured project continuation checkpoint")
    add_common_options(checkpoint)
    checkpoint.add_argument("--project", default="default")
    checkpoint.add_argument("--objective", required=True)
    checkpoint.add_argument("--verified-evidence", default="")
    checkpoint.add_argument("--remaining-gaps", default="")
    checkpoint.add_argument("--next-action", default="")
    checkpoint.add_argument("--prohibited-repetition", default="")
    checkpoint.add_argument("--expected-version", type=int)

    continuation = sub.add_parser("continue-prompt", help="Build a compact prompt for a new agent task")
    add_common_options(continuation)
    continuation.add_argument("--project", default="default")

    session_event = sub.add_parser("session-event", help="Append an immutable operational event")
    add_common_options(session_event)
    session_event.add_argument("--project", default="default")
    session_event.add_argument("--session-id", required=True)
    session_event.add_argument("--cursor", required=True)
    session_event.add_argument("--type", required=True)
    session_event.add_argument("--payload-json", default="{}")
    session_event.add_argument("--source", default="operator")
    session_event.add_argument("--verification-status", choices=("unverified", "verified", "failed", "stale"), default="unverified")

    session_events = sub.add_parser("session-events", help="Read append-only operational events")
    add_common_options(session_events)
    session_events.add_argument("--project", default="default")
    session_events.add_argument("--session-id")
    session_events.add_argument("--limit", type=int, default=100)

    codex_session = sub.add_parser("ingest-codex-session", help="Incrementally capture a local Codex JSONL session")
    add_common_options(codex_session)
    codex_session.add_argument("path")
    codex_session.add_argument("--project", default="default")
    codex_session.add_argument("--session-id")
    codex_session.add_argument("--max-events", type=int, default=5000)

    work_item = sub.add_parser("work-item", help="Create or update a structured operational work item")
    add_common_options(work_item)
    work_item.add_argument("external_id")
    work_item.add_argument("--project", default="default")
    work_item.add_argument("--item-type", default="asset")
    work_item.add_argument("--local-path")
    work_item.add_argument("--qa-state", default="unknown")
    work_item.add_argument("--decision", default="pending")
    work_item.add_argument("--attempt-count", type=int, default=0)
    work_item.add_argument("--fallback", default="")
    work_item.add_argument("--next-action", default="")

    reconcile = sub.add_parser("reconcile", help="Reconcile structured work state with the filesystem")
    add_common_options(reconcile)
    reconcile.add_argument("--project", default="default")

    readiness = sub.add_parser("operational-readiness", help="Separate database health from task continuation readiness")
    add_common_options(readiness)
    readiness.add_argument("--project", default="default")
    readiness.add_argument("--root", help="Active checkout root to verify before reporting continuation readiness")

    reflect_cmd = sub.add_parser("reflect", help="Consolidate duplicate memories and flag contradictions")
    add_common_options(reflect_cmd)
    reflect_cmd.add_argument("--project", default="default")

    policy = sub.add_parser("policy", help="Create, list, or retire typed governance policies")
    add_common_options(policy)
    policy.add_argument("action", choices=("add", "list", "retire"))
    policy.add_argument("--project", default="default")
    policy.add_argument("--id", type=int, dest="policy_id")
    policy.add_argument("--kind", choices=("constraint", "failed_approach", "fragile_path", "required_check", "prohibited_repetition"))
    policy.add_argument("--statement")
    policy.add_argument("--effect", choices=("warn", "block"), default="warn")
    policy.add_argument("--action-contains", default="")
    policy.add_argument("--path-glob", default="")
    policy.add_argument("--required-check", default="")
    policy.add_argument("--pramana", choices=("pratyaksha", "sabda", "anumana", "smriti", "kalpana"), default="smriti")
    policy.add_argument("--confidence", type=float, default=0.75)
    policy.add_argument("--verification-status", choices=("unverified", "verified", "failed", "stale"), default="unverified")
    policy.add_argument("--source-path")
    policy.add_argument("--source-hash")
    policy.add_argument("--verification-command")
    policy.add_argument("--expires-at")
    policy.add_argument("--non-overrideable", action="store_true")
    policy.add_argument("--include-retired", action="store_true")
    policy.add_argument("--reason")

    preflight_cmd = sub.add_parser("preflight", help="Evaluate an intended action against project governance")
    add_common_options(preflight_cmd)
    preflight_cmd.add_argument("action")
    preflight_cmd.add_argument("--project", default="default")
    preflight_cmd.add_argument("--path")
    preflight_cmd.add_argument("--check", action="append", default=[])
    preflight_cmd.add_argument("--operational-context", action="store_true", help="Warn on checkpoint, freshness, and Git readiness risks")
    preflight_cmd.add_argument("--override-reason")
    preflight_cmd.add_argument("--actor", default="operator")

    receipts_cmd = sub.add_parser("governance-receipts", help="List governance override receipts")
    add_common_options(receipts_cmd)
    receipts_cmd.add_argument("--project", default="default")
    receipts_cmd.add_argument("--limit", type=int, default=100)

    mcp_config = sub.add_parser("mcp-config", help="Generate an MCP host config snippet")
    add_common_options(mcp_config)
    mcp_config.add_argument("--project", default="default")
    mcp_config.add_argument("--name", default="rta-smriti")
    mcp_config.add_argument("--brain-dir", help="Generate one multi-project MCP gateway for this brain directory")
    mcp_config.add_argument("--root", help="Active checkout root that must match before configuration is emitted")

    mcp_doctor_cmd = sub.add_parser("mcp-doctor", help="Probe the exact generated MCP stdio server command")
    add_common_options(mcp_doctor_cmd)
    mcp_doctor_cmd.add_argument("--project", default="default")
    mcp_doctor_cmd.add_argument("--timeout", type=float, default=10.0)

    bootstrap = sub.add_parser("bootstrap-project", help="Create a per-project brain, index the repo, and optionally write project agent instructions")
    add_common_options(bootstrap)
    bootstrap.add_argument("path")
    bootstrap.add_argument("--project", required=True)
    bootstrap.add_argument("--brain-dir", default=str(Path.home() / "Documents" / "Codex" / "brains"))
    bootstrap.add_argument("--write-agents", action="store_true")
    bootstrap.add_argument("--embedding-provider", choices=("none", "hash", "sentence-transformers"), default="hash")

    start = sub.add_parser("start", help="Onboard a project and start its local brain in one command")
    start.add_argument("path")
    start.add_argument("--project")
    start.add_argument("--brain-dir", default=str(Path.home() / "Documents" / "Codex" / "brains"))
    start.add_argument("--target-agent", choices=tuple(sorted(SUPPORTED_TARGET_AGENTS)), default="universal")
    start.add_argument("--write-agents", action="store_true", help="Add the Rta-Smriti bridge to project agent files")
    start.add_argument("--embedding-provider", choices=("none", "hash", "sentence-transformers"), default="hash")
    start.add_argument("--interval", type=float, default=2.0)
    start.add_argument("--sessions-root", default=str(Path.home() / ".codex" / "sessions"))
    start.add_argument("--no-continuity", action="store_true", help="Do not start managed Codex task-continuity capture")
    start.add_argument("--continuity-interval", type=float, help="Continuity capture interval in seconds; defaults to --interval")
    start.add_argument("--continuity-inactivity", type=float, default=900.0)
    start.add_argument("--lookback-days", type=float, default=30.0, help="Initial Codex session lookback for continuity capture")
    start.add_argument("--backlog-tail-mb", type=float, default=2.0, help="Recent tail retained when a Codex session backlog is oversized")
    start.add_argument("--port", type=int, default=8765)
    start.add_argument("--no-open", action="store_true")
    start.add_argument("--no-watcher", action="store_true")
    start.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit stable JSON")

    self_check_cmd = sub.add_parser("self-check", help="Verify that a project brain is ready to use")
    add_common_options(self_check_cmd)
    self_check_cmd.add_argument("--project", default="default")
    self_check_cmd.add_argument("--check-files", action="store_true", help="Hash indexed files to include fresh/changed/missing counts")
    self_check_cmd.add_argument("--root", help="Active checkout root to verify before reporting readiness")

    projects = sub.add_parser("projects-list", help="List projects registered in a brain database")
    add_common_options(projects)

    install = sub.add_parser("install-local", help="Install local command wrappers into a target folder")
    add_common_options(install)
    install.add_argument("--target", default=str(Path.home() / ".local" / "bin"))

    doctor_cmd = sub.add_parser("doctor", help="Verify local brain health")
    add_common_options(doctor_cmd)
    doctor_cmd.add_argument("--project", help="Also evaluate task continuation readiness for one project")
    doctor_cmd.add_argument("--root", help="Active checkout root to verify when --project is supplied")

    publish = sub.add_parser("publish-readiness", help="Check whether this package is ready to publish on GitHub")
    add_common_options(publish)

    dashboard = sub.add_parser("dashboard", help="Run the local operator console", description="Run the local operator console")
    dashboard.add_argument("--brain-dir", default=str(Path.home() / "Documents" / "Codex" / "brains"))
    dashboard.add_argument("--db", default=argparse.SUPPRESS, help="Default brain DB for the opened console")
    dashboard.add_argument("--project", default=None, help="Default project for the opened console")
    dashboard.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1", help="Loopback host only")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")

    console = sub.add_parser("console", help="Manage the terminal-independent operator console")
    console.add_argument(
        "action",
        choices=("start", "open", "status", "restart", "stop", "login-enable", "login-disable", "login-status"),
    )
    console.add_argument("--brain-dir", default=str(Path.home() / "Documents" / "Codex" / "brains"))
    console.add_argument("--db", default=argparse.SUPPRESS, help="Default brain DB for the opened console")
    console.add_argument("--project", default=None, help="Default project for the opened console")
    console.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1")
    console.add_argument("--port", type=int, default=8765)
    console.add_argument("--no-open", action="store_true", help="Do not open the browser")
    console.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit stable JSON")

    console_worker = sub.add_parser("_console-worker", help=argparse.SUPPRESS)
    console_worker.add_argument("--tool-root", required=True)
    console_worker.add_argument("--brain-dir", required=True)
    console_worker.add_argument("--default-db")
    console_worker.add_argument("--default-project")
    console_worker.add_argument("--host", required=True)
    console_worker.add_argument("--port", type=int, required=True)
    console_worker.add_argument("--state-file", required=True)
    console_worker.add_argument("--stop-file", required=True)
    console_worker.add_argument("--lock-file", required=True)
    console_worker.add_argument("--token-file", required=True)
    return parser


def build_mcp_config(db_path: str, project: str, name: str) -> dict:
    return mcp_config_payload(db_path, project, name, tool_root())


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        try:
            payload = onboard_project(
                tool_root(),
                Path(args.path),
                brain_dir=Path(args.brain_dir),
                project=args.project,
                target_agent=args.target_agent,
                write_agents=args.write_agents,
                embedding_provider=args.embedding_provider,
                watcher_interval=args.interval,
                sessions_root=Path(args.sessions_root),
                start_continuity_capture=not args.no_continuity,
                continuity_interval=args.continuity_interval,
                continuity_inactivity=args.continuity_inactivity,
                continuity_lookback_days=args.lookback_days,
                continuity_backlog_tail_bytes=int(args.backlog_tail_mb * 1_000_000),
                port=args.port,
                open_browser=not args.no_open,
                start_sync=not args.no_watcher,
            )
            emit(payload, args.json)
            return 0 if payload.get("ready") else 1
        except Exception as exc:
            error = {"status": "error", "ready": False, "error": {"type": exc.__class__.__name__, "message": str(exc)}}
            if getattr(args, "json", False):
                print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "_console-worker":
        return run_console_worker(
            Path(args.tool_root),
            Path(args.brain_dir),
            Path(args.default_db) if args.default_db else None,
            args.default_project,
            args.host,
            args.port,
            Path(args.state_file),
            Path(args.stop_file),
            Path(args.lock_file),
            Path(args.token_file),
        )
    if args.command == "console":
        try:
            brain_dir = Path(args.brain_dir)
            if args.action == "login-status":
                payload = autostart_status(brain_dir)
            elif args.action == "login-enable":
                payload = enable_autostart(tool_root(), brain_dir)
            elif args.action == "login-disable":
                payload = disable_autostart(brain_dir)
            elif args.action == "status":
                payload = console_status(brain_dir)
            elif args.action == "open":
                payload = open_console(brain_dir, launch_browser=not args.no_open)
            elif args.action == "stop":
                payload = stop_console(brain_dir)
            else:
                operation = restart_console if args.action == "restart" else start_console
                payload = operation(
                    tool_root(),
                    brain_dir,
                    default_db=Path(args.db) if args.db else None,
                    default_project=args.project,
                    host=args.host,
                    port=args.port,
                    open_browser=not args.no_open,
                )
            emit(payload, args.json)
            return 0
        except Exception as exc:
            error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
            if getattr(args, "json", False):
                print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "dashboard":
        run_dashboard(
            tool_root(),
            Path(args.brain_dir),
            default_db=Path(args.db) if args.db else None,
            default_project=args.project,
            host=args.host,
            port=args.port,
            open_browser=not args.no_open,
        )
        return 0
    if args.command == "publish-readiness":
        emit(publish_readiness(tool_root()), args.json)
        return 0
    if args.command == "_watch-worker":
        return run_watcher_worker(
            Path(args.db),
            Path(args.root),
            args.project,
            Path(args.state_file),
            Path(args.stop_file),
            Path(args.lock_file),
            args.interval,
        )
    if args.command == "_continuity-worker":
        return run_continuity_worker(
            Path(args.db), Path(args.root), args.project, Path(args.sessions_root),
            Path(args.state_file), Path(args.stop_file), Path(args.lock_file),
            args.interval, args.inactivity, args.lookback_days, args.backlog_tail_bytes,
        )
    if args.command == "watcher":
        try:
            db_path = Path(args.db).expanduser().resolve()
            if args.action == "status":
                payload = watcher_status(db_path, args.project)
            elif args.action == "stop":
                payload = stop_watcher(db_path, args.project)
            else:
                root = Path(args.path).expanduser().resolve() if args.path else None
                if root is None:
                    conn = connect(db_path)
                    try:
                        row = conn.execute(
                            "SELECT root_path FROM projects WHERE name = ?", (args.project,)
                        ).fetchone()
                    finally:
                        conn.close()
                    if not row or not row["root_path"]:
                        raise ValueError("project has no bound repository path; provide a path")
                    root = Path(row["root_path"])
                payload = start_watcher(db_path, root, args.project, args.interval)
            emit(payload, args.json)
            return 0
        except Exception as exc:
            error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
            if getattr(args, "json", False):
                print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "continuity":
        try:
            db_path = Path(args.db).expanduser().resolve()
            if args.action == "status":
                payload = continuity_status(db_path, args.project)
            elif args.action == "stop":
                payload = stop_continuity(db_path, args.project)
            else:
                root = Path(args.root).expanduser().resolve() if args.root else None
                if root is None:
                    conn = connect(db_path)
                    try:
                        row = conn.execute("SELECT root_path FROM projects WHERE name = ?", (args.project,)).fetchone()
                    finally:
                        conn.close()
                    if not row or not row["root_path"]:
                        raise ValueError("project has no bound repository path; provide --root")
                    root = Path(row["root_path"])
                payload = start_continuity(
                    db_path, root, args.project, Path(args.sessions_root),
                    interval_seconds=args.interval, inactivity_seconds=args.inactivity,
                    lookback_days=args.lookback_days,
                    backlog_tail_bytes=int(args.backlog_tail_mb * 1_000_000),
                )
            emit(payload, args.json)
            return 0
        except Exception as exc:
            error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
            if getattr(args, "json", False):
                print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "benchmark":
        try:
            payload = run_public_benchmark(
                Path(args.dataset), include_semantic=args.include_semantic,
                semantic_model=args.semantic_model,
            )
            history = None
            if args.history:
                history = append_benchmark_history(payload, Path(args.history), label=args.label)
                payload = {**payload, "history": history}
            if args.report:
                if history is None and args.history and Path(args.history).is_file():
                    history = benchmark_history(Path(args.history))
                payload = {**payload, "report": write_benchmark_report(payload, Path(args.report), history=history)}
            emit(payload, args.json)
            return 0
        except Exception as exc:
            error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
            if getattr(args, "json", False):
                print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
    if args.command == "snapshot":
        try:
            if args.action == "keygen":
                if not args.public_key:
                    raise ValueError("snapshot keygen requires --public-key")
                payload = snapshot_keygen(Path(args.path), Path(args.public_key))
            elif args.action == "passphrase-keygen":
                payload = snapshot_passphrase_keygen(Path(args.path))
            elif args.action == "create":
                payload = snapshot_create(
                    Path(args.db), Path(args.path),
                    key_path=Path(args.key) if args.key else None,
                    private_key_path=Path(args.private_key) if args.private_key else None,
                )
            elif args.action == "verify":
                payload = snapshot_verify(
                    Path(args.path),
                    key_path=Path(args.key) if args.key else None,
                    public_key_path=Path(args.public_key) if args.public_key else None,
                )
            elif args.action == "encrypt":
                if not args.passphrase:
                    raise ValueError("snapshot encrypt requires --passphrase")
                payload = snapshot_create_encrypted(
                    Path(args.db), Path(args.path), passphrase_path=Path(args.passphrase),
                    private_key_path=Path(args.private_key) if args.private_key else None,
                )
            elif args.action == "verify-encrypted":
                if not args.passphrase:
                    raise ValueError("encrypted snapshot verification requires --passphrase")
                payload = snapshot_verify_encrypted(
                    Path(args.path), passphrase_path=Path(args.passphrase),
                    public_key_path=Path(args.public_key) if args.public_key else None,
                )
            else:
                if not args.passphrase or not args.output_db:
                    raise ValueError("snapshot restore requires --passphrase and --output-db")
                payload = snapshot_restore_encrypted(
                    Path(args.path), Path(args.output_db), passphrase_path=Path(args.passphrase),
                    public_key_path=Path(args.public_key) if args.public_key else None,
                )
            emit(payload, args.json)
            return 0
        except Exception as exc:
            error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
            if getattr(args, "json", False):
                print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
            else:
                print(f"error: {exc}", file=sys.stderr)
            return 1
    exit_code = 0
    try:
        conn = connect(Path(args.db))
        with conn:
            if args.command == "init":
                if args.rebind_root:
                    raise ValueError("--rebind-root is retired for init; use root-rebind with a no-clobber backup path")
                payload = init_project(conn, args.project, str(Path(args.root).resolve()), allow_root_rebind=args.rebind_root)
            elif args.command == "remember":
                provenance = None
                if any((args.source_path, args.source_hash, args.verification_command, args.verification_timestamp)) or args.verification_status != "unverified":
                    provenance = {
                        "source_path": args.source_path,
                        "source_hash": args.source_hash,
                        "command": args.verification_command,
                        "timestamp": args.verification_timestamp,
                        "verification_status": args.verification_status,
                    }
                payload = remember(
                    conn,
                    args.text,
                    project=args.project,
                    memory_type=args.type,
                    pramana=args.pramana,
                    confidence=args.confidence,
                    priority=args.priority,
                    provenance=provenance,
                )
            elif args.command == "ingest-repo":
                if args.rebind_root:
                    raise ValueError("--rebind-root is retired for ingest-repo; use root-rebind with a no-clobber backup path")
                payload = ingest_repo(
                    conn,
                    Path(args.path),
                    project=args.project,
                    force=args.force,
                    repair_deep_stale=args.repair_deep_stale,
                    allow_root_rebind=args.rebind_root,
                )
            elif args.command == "root-rebind":
                payload = rebind_project_root(
                    conn, Path(args.path), project=args.project, backup_path=Path(args.backup),
                )
            elif args.command == "watch-repo":
                payload = watch_repository(conn, Path(args.path), project=args.project, interval_seconds=args.interval)
            elif args.command == "settings":
                changes = {}
                if args.max_file_mb is not None:
                    changes["max_file_bytes"] = round(args.max_file_mb * 1_000_000)
                for argument, key in (
                    (args.large_file_policy, "large_file_policy"),
                    (args.parser_adapter, "parser_adapter"),
                    (args.lsp_command, "lsp_command"),
                    (args.lsp_auto_discovery, "lsp_auto_discovery"),
                    (args.embedding_provider, "embedding_provider"),
                    (args.embedding_model, "embedding_model"),
                    (args.hybrid_weight, "hybrid_weight"),
                    (args.compaction_provider, "compaction_provider"),
                    (args.compaction_model, "compaction_model"),
                    (args.compaction_endpoint, "compaction_endpoint"),
                    (args.compaction_timeout, "compaction_timeout_seconds"),
                ):
                    if argument is not None:
                        changes[key] = argument
                payload = update_project_settings(conn, args.project, changes) if changes else get_project_settings(conn, args.project)
            elif args.command == "ingest-thread":
                payload = ingest_thread(conn, Path(args.path), project=args.project, title=args.title)
            elif args.command == "search":
                payload = search(conn, args.query, project=args.project, limit=args.limit)
            elif args.command == "graph":
                payload = graph(conn, project=args.project, limit=args.limit)
            elif args.command == "graph-query":
                payload = graph_query(
                    conn, project=args.project, query_type=args.query_type,
                    target=args.target, depth=args.depth, limit=args.limit,
                )
            elif args.command == "retrieval-diagnostics":
                payload = retrieval_diagnostics(conn, args.query, project=args.project, limit=args.limit)
            elif args.command == "workspace":
                if args.action == "list":
                    payload = list_workspaces(conn)
                elif not args.name:
                    raise ValueError("workspace action requires --name")
                elif args.action == "create":
                    payload = create_workspace(conn, args.name, args.description)
                elif args.action == "add":
                    if not args.project:
                        raise ValueError("workspace add requires --project")
                    payload = add_project_to_workspace(
                        conn, workspace=args.name, project=args.project, role=args.role, db_path=args.member_db,
                    )
                elif args.action == "remove":
                    if not args.project:
                        raise ValueError("workspace remove requires --project")
                    payload = remove_project_from_workspace(
                        conn, workspace=args.name, project=args.project, db_path=args.member_db,
                    )
                elif args.action == "delete":
                    payload = delete_workspace(conn, args.name)
                elif args.action == "health":
                    payload = workspace_health(conn, args.name)
                elif args.action == "search":
                    if not args.query:
                        raise ValueError("workspace search requires --query")
                    payload = search_workspace(conn, workspace=args.name, query=args.query, limit_per_project=args.limit)
                else:
                    payload = get_workspace(conn, args.name)
            elif args.command == "bundle-export":
                payload = export_bundle(
                    conn, Path(args.output), projects=args.projects,
                    include=tuple(args.include or ("memories", "checkpoints", "policies")), redact=not args.no_redact,
                    preview=args.preview,
                )
            elif args.command == "bundle-import":
                payload = (
                    inspect_bundle(Path(args.source), conn=conn)
                    if args.preview else import_bundle(conn, Path(args.source), conflict=args.conflict)
                )
            elif args.command == "git-hooks":
                payload = (
                    install_git_hooks(Path(args.root), db_path=Path(args.db), project=args.project)
                    if args.action == "install" else uninstall_git_hooks(Path(args.root))
                )
            elif args.command == "memory-feedback":
                payload = apply_memory_feedback(
                    conn, project=args.project, memory_id=args.memory_id,
                    outcome=args.outcome, evidence=args.evidence,
                )
            elif args.command == "memory-decay":
                payload = run_conservative_decay(
                    conn, project=args.project, minimum_age_days=args.minimum_age_days, step=args.step,
                )
            elif args.command == "context-pack":
                payload = build_context_pack(
                    conn, args.task, project=args.project, limit=args.limit, max_tokens=args.max_tokens
                )
            elif args.command == "stale-check":
                payload = stale_check(
                    conn,
                    project=args.project,
                    deep=bool(args.deep or args.rehash),
                    refresh_hashes=args.rehash,
                    detail_limit=args.detail_limit,
                    include_fresh_details=args.details,
                    active_root=Path(args.root) if args.root else None,
                )
            elif args.command == "truth":
                if args.truth_action == "assert":
                    payload = append_claim(
                        conn,
                        project=args.project,
                        active_root=Path(args.root),
                        claim_id=args.claim_id,
                        subject=args.subject,
                        predicate=args.predicate,
                        value=parse_json_argument("--value-json", args.value_json),
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        valid_from=args.valid_from,
                        valid_to=args.valid_to,
                        expires_at=args.expires_at,
                        epistemic_state=args.state,
                        confidence=args.confidence,
                        actor_type=args.actor_type,
                        actor_id=args.actor_id,
                        source="cli",
                    )
                elif args.truth_action == "current":
                    payload = truth_current(
                        conn,
                        project=args.project,
                        claim_id=args.claim_id,
                        valid_at=args.valid_at,
                    )
                elif args.truth_action == "state":
                    payload = change_claim_state(
                        conn,
                        project=args.project,
                        active_root=Path(args.root),
                        claim_id=args.claim_id,
                        new_state=args.state,
                        reason=args.reason,
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        actor_type=args.actor_type,
                        actor_id=args.actor_id,
                        source="cli",
                    )
                elif args.truth_action == "history":
                    payload = truth_history(
                        conn,
                        project=args.project,
                        claim_id=args.claim_id,
                        limit=args.limit,
                    )
                elif args.truth_action == "as-of":
                    payload = truth_as_of(
                        conn,
                        project=args.project,
                        claim_id=args.claim_id,
                        valid_at=args.valid_at,
                        recorded_sequence=args.recorded_sequence,
                    )
                elif args.truth_action == "revise":
                    payload = revise_claim(
                        conn,
                        project=args.project,
                        active_root=Path(args.root),
                        claim_id=args.claim_id,
                        value=parse_json_argument("--value-json", args.value_json),
                        reason=args.reason,
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        valid_from=args.valid_from,
                        valid_to=args.valid_to,
                        actor_type=args.actor_type,
                        actor_id=args.actor_id,
                        source="cli",
                    )
                elif args.truth_action == "relate":
                    payload = relate_claims(
                        conn,
                        project=args.project,
                        active_root=Path(args.root),
                        relation_id=args.relation_id,
                        from_claim_id=args.from_claim,
                        relation_type=args.type,
                        to_claim_id=args.to_claim,
                        confidence=args.confidence,
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        actor_type=args.actor_type,
                        actor_id=args.actor_id,
                        source="cli",
                    )
                elif args.truth_action == "evidence":
                    provenance = parse_json_argument("--provenance-json", args.provenance_json)
                    if not isinstance(provenance, dict):
                        raise ValueError("--provenance-json must contain a JSON object")
                    payload = attach_evidence(
                        conn,
                        project=args.project,
                        active_root=Path(args.root),
                        claim_id=args.claim_id,
                        evidence_id=args.evidence_id,
                        source_identifier=args.source_identifier,
                        source_hash=args.source_hash,
                        method=args.method,
                        polarity=args.polarity,
                        authority_class=args.authority_class,
                        confidence=args.confidence,
                        uncertainty=args.uncertainty,
                        provenance=provenance,
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        verification_status=args.verification_status,
                        actor_type=args.actor_type,
                        actor_id=args.actor_id,
                        source="cli",
                    )
                elif args.truth_action == "abstain":
                    missing = parse_json_argument("--missing-evidence-json", args.missing_evidence_json)
                    conflicts = parse_json_argument("--unresolved-conflicts-json", args.unresolved_conflicts_json)
                    if not isinstance(missing, list) or not isinstance(conflicts, list):
                        raise ValueError("abstention evidence and conflicts must be JSON arrays")
                    payload = record_abstention(
                        conn,
                        project=args.project,
                        active_root=Path(args.root),
                        abstention_id=args.abstention_id,
                        query_scope=args.query_scope,
                        missing_evidence=missing,
                        unresolved_conflicts=conflicts,
                        minimum_revalidation_action=args.minimum_revalidation_action,
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        actor_type=args.actor_type,
                        actor_id=args.actor_id,
                        source="cli",
                    )
                elif args.truth_action == "explain":
                    payload = truth_explain(
                        conn, project=args.project, claim_id=args.claim_id,
                        valid_at=args.valid_at,
                    )
                elif args.truth_action == "diff":
                    payload = truth_diff(
                        conn, project=args.project,
                        from_sequence=args.from_sequence,
                        to_sequence=args.to_sequence,
                        valid_at=args.valid_at,
                        limit=args.limit,
                    )
                elif args.truth_action == "anchor":
                    payload = observe_repository_anchor(
                        conn, project=args.project, active_root=Path(args.root),
                        anchor_id=args.anchor_id,
                        idempotency_key=args.idempotency_key,
                        expected_stream_version=args.expected_version,
                        actor_type="operator", actor_id="local-operator", source="cli",
                    )
                elif args.truth_action == "at-commit":
                    payload = truth_at_commit(
                        conn, project=args.project, claim_id=args.claim_id,
                        commit=args.commit, valid_at=args.valid_at,
                    )
                elif args.truth_action == "validator":
                    if args.validator_action == "add":
                        config = parse_json_argument("--config-json", args.config_json)
                        if not isinstance(config, dict):
                            raise ValueError("--config-json must contain a JSON object")
                        payload = define_validator(
                            conn, project=args.project, active_root=Path(args.root),
                            validator_id=args.validator_id, validator_type=args.type,
                            claim_id=args.claim_id, config=config,
                            failure_effect=args.failure_effect,
                            idempotency_key=args.idempotency_key,
                            expected_stream_version=args.expected_version,
                            actor_type="operator", actor_id=args.actor_id, source="cli",
                        )
                    elif args.validator_action == "run":
                        payload = run_validator(
                            conn, project=args.project, active_root=Path(args.root),
                            validator_id=args.validator_id,
                            idempotency_key=args.idempotency_key,
                            expected_stream_version=args.expected_version,
                            allow_command=args.allow_command,
                            trusted_executables=tuple(args.trusted_executable),
                            actor_type="operator", actor_id=args.actor_id, source="cli",
                        )
                    else:
                        payload = validator_history(
                            conn, project=args.project,
                            validator_id=args.validator_id, limit=args.limit,
                        )
                elif args.truth_action == "ledger":
                    payload = verify_ledger(conn, project=args.project)
                elif args.truth_action == "projection":
                    if args.projection_action == "rebuild":
                        payload = rebuild_projections(
                            conn, project=args.project, active_root=Path(args.root),
                        )
                    else:
                        payload = verify_ledger(conn, project=args.project)
                else:
                    raise ValueError(f"unsupported truth action: {args.truth_action}")
            elif args.command == "integrity-diagnostics":
                payload = integrity_diagnostics(
                    conn, project=args.project, active_root=Path(args.root) if args.root else None,
                )
            elif args.command == "checkpoint":
                payload = save_checkpoint(
                    conn,
                    project=args.project,
                    objective=args.objective,
                    verified_evidence=args.verified_evidence,
                    remaining_gaps=args.remaining_gaps,
                    next_action=args.next_action,
                    prohibited_repetition=args.prohibited_repetition,
                    expected_version=args.expected_version,
                )
            elif args.command == "continue-prompt":
                payload = build_continuation_prompt(conn, project=args.project)
            elif args.command == "session-event":
                payload = append_event(
                    conn, args.project, args.session_id, args.cursor, args.type,
                    json.loads(args.payload_json), source=args.source,
                    verification_status=args.verification_status,
                )
            elif args.command == "session-events":
                payload = list_events(conn, args.project, session_id=args.session_id, limit=args.limit)
            elif args.command == "ingest-codex-session":
                payload = ingest_codex_session(
                    conn, Path(args.path), args.project,
                    session_id=args.session_id, max_events=args.max_events,
                )
            elif args.command == "work-item":
                payload = upsert_work_item(
                    conn, args.project, args.item_type, args.external_id,
                    local_path=args.local_path, qa_state=args.qa_state, decision=args.decision,
                    attempt_count=args.attempt_count, fallback=args.fallback, next_action=args.next_action,
                )
            elif args.command == "reconcile":
                payload = reconcile_work_items(conn, args.project)
            elif args.command == "operational-readiness":
                payload = operational_readiness(
                    conn, args.project, lifecycle=continuity_status(Path(args.db), args.project),
                    active_root=Path(args.root) if args.root else None,
                )
            elif args.command == "reflect":
                payload = reflect(conn, project=args.project)
            elif args.command == "policy":
                if args.action == "list":
                    payload = list_policies(conn, project=args.project, include_retired=args.include_retired)
                elif args.action == "retire":
                    if args.policy_id is None or not args.reason:
                        raise ValueError("policy retire requires --id and --reason")
                    payload = retire_policy(conn, project=args.project, policy_id=args.policy_id, reason=args.reason)
                else:
                    if not args.kind or not args.statement:
                        raise ValueError("policy add requires --kind and --statement")
                    payload = create_policy(
                        conn,
                        project=args.project,
                        kind=args.kind,
                        statement=args.statement,
                        effect=args.effect,
                        action_contains=args.action_contains,
                        path_glob=args.path_glob,
                        required_check=args.required_check,
                        pramana=args.pramana,
                        confidence=args.confidence,
                        provenance={
                            "verification_status": args.verification_status,
                            "source_path": args.source_path,
                            "source_hash": args.source_hash,
                            "command": args.verification_command,
                        },
                        overrideable=not args.non_overrideable,
                        expires_at=args.expires_at,
                    )
            elif args.command == "preflight":
                payload = preflight(
                    conn,
                    project=args.project,
                    action=args.action,
                    path=args.path,
                    completed_checks=args.check,
                    override_reason=args.override_reason,
                    actor=args.actor,
                    operational_context=(
                        build_operational_context(conn, args.project, db_path=args.db)
                        if args.operational_context else None
                    ),
                )
                if payload["decision"] == "block":
                    exit_code = 2
            elif args.command == "governance-receipts":
                payload = list_receipts(conn, project=args.project, limit=args.limit)
            elif args.command == "mcp-config":
                if args.root and not args.brain_dir:
                    binding = project_binding_status(conn, args.project, Path(args.root))
                    if not binding["ready"]:
                        raise ValueError(
                            f"active checkout mismatch ({binding['state']}); verify or rebind the project root first"
                        )
                payload = (
                    mcp_gateway_config_payload(args.brain_dir, args.name, tool_root())
                    if args.brain_dir else build_mcp_config(args.db, args.project, args.name)
                )
            elif args.command == "mcp-doctor":
                payload = mcp_doctor(Path(args.db), args.project, tool_root(), timeout=args.timeout)
            elif args.command == "bootstrap-project":
                payload = bootstrap_project(
                    conn,
                    Path(args.path),
                    args.project,
                    Path(args.brain_dir),
                    args.write_agents,
                    tool_root(),
                    embedding_provider=args.embedding_provider,
                )
            elif args.command == "self-check":
                payload = self_check(
                    conn, project=args.project, check_files=args.check_files,
                    active_root=Path(args.root) if args.root else None,
                )
            elif args.command == "projects-list":
                payload = projects_list(conn)
            elif args.command == "install-local":
                payload = install_local(Path(args.target), tool_root())
            elif args.command == "doctor":
                payload = doctor(conn)
                if args.project:
                    payload["operational"] = operational_readiness(
                        conn, args.project, lifecycle=continuity_status(Path(args.db), args.project),
                        active_root=Path(args.root) if args.root else None,
                    )
            else:
                parser.error(f"unknown command: {args.command}")
                return 2
        emit(payload, args.json)
        return exit_code
    except Exception as exc:
        error = {"status": "error", "error": {"type": exc.__class__.__name__, "message": str(exc)}}
        if getattr(args, "json", False):
            print(json.dumps(error, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
