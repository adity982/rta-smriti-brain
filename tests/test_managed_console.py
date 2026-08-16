import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from rta_brain.console_daemon import (
    _worker_command,
    console_paths,
    console_status,
    open_console,
    restart_console,
    start_console,
    stop_console,
)
from rta_brain.db import connect, ingest_repo, init_project, remember
from rta_brain.runtime_control import (
    SpawnedWorker,
    detach_current_worker_session,
    detached_process_kwargs,
    detached_worker_bootstrap,
    process_alive,
    read_json,
    spawn_detached_worker,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]


class RuntimeControlTests(unittest.TestCase):
    def test_source_console_worker_uses_the_minimal_entry_point(self):
        command = _worker_command(
            ROOT,
            Path("brains"),
            None,
            None,
            "127.0.0.1",
            0,
            {
                "state": Path("state.json"),
                "stop": Path("stop.request"),
                "lock": Path("launch.lock"),
                "token": Path("capability.secret"),
            },
        )
        self.assertTrue(any("rta_brain.console_worker" in part for part in command))
        self.assertNotIn("rta_brain.cli", command)

    def test_json_state_write_is_atomic_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "control" / "state.json"
            write_json(state, {"state": "running", "pid": os.getpid()})
            self.assertEqual(read_json(state)["state"], "running")
            self.assertEqual(list(state.parent.glob(".*.tmp")), [])

    def test_json_state_rejects_a_hard_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = Path(tmp) / "victim.json"
            victim.write_text('{"keep": true}\n', encoding="utf-8")
            state = Path(tmp) / "state.json"
            os.link(victim, state)
            with self.assertRaisesRegex(ValueError, "linked runtime state"):
                write_json(state, {"state": "running"})
            self.assertEqual(json.loads(victim.read_text(encoding="utf-8")), {"keep": True})

    def test_process_liveness_probe_is_non_destructive(self):
        self.assertTrue(process_alive(os.getpid()))
        self.assertFalse(process_alive(-1))

    def test_detached_spawn_options_are_platform_specific(self):
        options = detached_process_kwargs()
        if os.name == "nt":
            self.assertGreater(options["creationflags"], 0)
            self.assertNotIn("start_new_session", options)
        elif sys.platform == "darwin":
            self.assertEqual(options, {})
        else:
            self.assertTrue(options["start_new_session"])
            self.assertNotIn("creationflags", options)

    def test_macos_launch_detaches_in_fresh_worker_and_uses_posix_spawn_options(self):
        with patch("rta_brain.runtime_control.sys.platform", "darwin"):
            bootstrap = detached_worker_bootstrap("rta_brain.worker", Path("trusted-root"))
            self.assertIn("os.setsid()", bootstrap)
            self.assertIn("runpy.run_module('rta_brain.worker'", bootstrap)

    def test_macos_worker_session_detach_is_idempotent(self):
        with (
            patch("rta_brain.runtime_control.sys.platform", "darwin"),
            patch("rta_brain.runtime_control.os.getpid", return_value=41),
            patch("rta_brain.runtime_control.os.getsid", side_effect=(9, 41), create=True),
            patch("rta_brain.runtime_control.os.setsid", create=True) as setsid,
        ):
            detach_current_worker_session()
            detach_current_worker_session()
        setsid.assert_called_once_with()

    def test_macos_worker_uses_posix_spawn_with_explicit_stdio_actions(self):
        log_stream = MagicMock()
        log_stream.fileno.return_value = 72
        with (
            patch("rta_brain.runtime_control.sys.platform", "darwin"),
            patch("rta_brain.runtime_control.os.open", return_value=71),
            patch("rta_brain.runtime_control.os.close") as close,
            patch("rta_brain.runtime_control.os.posix_spawn", return_value=1234, create=True) as spawn,
            patch("rta_brain.runtime_control.os.POSIX_SPAWN_DUP2", 2, create=True),
            patch("rta_brain.runtime_control.os.POSIX_SPAWN_CLOSE", 1, create=True),
        ):
            process = spawn_detached_worker(
                ["/trusted/python", "-I", "-c", "pass"],
                log_stream,
                {"SAFE": "1"},
                Path("ignored-on-darwin"),
            )
        self.assertEqual(process.pid, 1234)
        spawn.assert_called_once_with(
            "/trusted/python",
            ["/trusted/python", "-I", "-c", "pass"],
            {"SAFE": "1"},
            file_actions=[(2, 71, 0), (2, 72, 1), (2, 72, 2), (1, 71), (1, 72)],
        )
        close.assert_called_once_with(71)

    def test_spawned_worker_reports_exit_and_forwards_signals(self):
        process = SpawnedWorker(1234)
        with (
            patch("rta_brain.runtime_control.os.WNOHANG", 1, create=True),
            patch("rta_brain.runtime_control.os.waitpid", return_value=(1234, 256)),
            patch("rta_brain.runtime_control.os.waitstatus_to_exitcode", return_value=1),
        ):
            self.assertEqual(process.poll(), 1)
            self.assertEqual(process.wait(timeout=0.1), 1)
        with patch("rta_brain.runtime_control.os.kill") as kill:
            with (
                patch("rta_brain.runtime_control.signal.SIGTERM", 15, create=True),
                patch("rta_brain.runtime_control.signal.SIGKILL", 9, create=True),
            ):
                process.terminate()
                process.kill()
        self.assertEqual(kill.call_count, 2)


class ManagedConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self.tempdir.name) / "brains"
        self.brain_dir.mkdir()

    def tearDown(self):
        try:
            stop_console(self.brain_dir, timeout=5.0)
        except Exception:
            pass
        self.tempdir.cleanup()

    def test_stopped_status_contains_no_capability_material(self):
        status = console_status(self.brain_dir)
        self.assertEqual(status["state"], "stopped")
        self.assertNotIn("token", json.dumps(status).lower())
        self.assertNotIn("#token=", json.dumps(status))

    def test_linked_console_log_is_rejected_without_modifying_victim(self):
        paths = console_paths(self.brain_dir)
        paths["directory"].mkdir()
        victim = Path(self.tempdir.name) / "victim.log"
        victim.write_text("keep\n", encoding="utf-8")
        os.link(victim, paths["log"])
        with self.assertRaisesRegex(ValueError, "linked console log"):
            start_console(ROOT, self.brain_dir, port=0, open_browser=False)
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")

    def test_start_open_status_restart_and_stop_lifecycle(self):
        started = start_console(
            ROOT,
            self.brain_dir,
            port=0,
            open_browser=False,
            startup_timeout=10.0,
        )
        self.assertEqual(started["state"], "running")
        self.assertTrue(process_alive(started["pid"]))
        self.assertRegex(started["url"], r"^http://127\.0\.0\.1:\d+/#token=")

        status = console_status(self.brain_dir)
        self.assertEqual(status["state"], "running")
        self.assertEqual(status["port"], started["port"])
        self.assertNotIn("token", json.dumps(status).lower())
        self.assertNotIn("url", status)

        request = urllib.request.Request(
            f"http://127.0.0.1:{started['port']}/api/projects",
            headers={"X-Rta-Smriti-Token": started["url"].split("#token=", 1)[1]},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIsNone(response.headers.get("Set-Cookie"))

        health_request = urllib.request.Request(
            f"http://127.0.0.1:{started['port']}/api/runtime-health",
            headers={"X-Rta-Smriti-Token": started["url"].split("#token=", 1)[1]},
        )
        with urllib.request.urlopen(health_request, timeout=5) as response:
            runtime_health = json.loads(response.read().decode("utf-8"))
        self.assertEqual(runtime_health["instance_id"], started["instance_id"])

        with patch("rta_brain.console_daemon.webbrowser.open", return_value=True) as browser_open:
            opened = open_console(self.brain_dir, launch_browser=True)
        browser_open.assert_called_once_with(opened["url"])
        self.assertEqual(opened["port"], started["port"])

        restarted = restart_console(
            ROOT,
            self.brain_dir,
            port=0,
            open_browser=False,
            startup_timeout=10.0,
        )
        self.assertEqual(restarted["state"], "running")
        self.assertNotEqual(restarted["pid"], started["pid"])

        stopped = stop_console(self.brain_dir, timeout=10.0)
        self.assertEqual(stopped["state"], "stopped")

    def test_occupied_preferred_port_recovers_to_an_available_port(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        occupied = int(listener.getsockname()[1])
        try:
            started = start_console(
                ROOT,
                self.brain_dir,
                port=occupied,
                open_browser=False,
                startup_timeout=10.0,
            )
        finally:
            listener.close()
        self.assertEqual(started["state"], "running")
        self.assertNotEqual(started["port"], occupied)

    def test_unauthorized_api_request_is_rejected(self):
        started = start_console(ROOT, self.brain_dir, port=0, open_browser=False, startup_timeout=10.0)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                f"http://127.0.0.1:{started['port']}/api/projects",
                timeout=5,
            )
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_console_rejects_non_object_json_without_internal_error(self):
        started = start_console(ROOT, self.brain_dir, port=0, open_browser=False, startup_timeout=10.0)
        token = started["url"].split("#token=", 1)[1]
        request = urllib.request.Request(
            f"http://127.0.0.1:{started['port']}/api/preflight",
            data=b"[]",
            headers={"X-Rta-Smriti-Token": token, "Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        payload = json.loads(caught.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"]["type"], "ValueError")
        caught.exception.close()

    def test_governance_api_supports_policy_preflight_override_and_retirement(self):
        db_path = self.brain_dir / "demo.sqlite"
        conn = connect(db_path)
        try:
            init_project(conn, "demo", self.tempdir.name)
        finally:
            conn.close()
        started = start_console(ROOT, self.brain_dir, port=0, open_browser=False, startup_timeout=10.0)
        token = started["url"].split("#token=", 1)[1]
        base_url = f"http://127.0.0.1:{started['port']}"
        headers = {"X-Rta-Smriti-Token": token, "Content-Type": "application/json"}

        def post(path, payload):
            request = urllib.request.Request(
                base_url + path,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        project_ref = {"db_path": str(db_path), "project": "demo"}
        created = post("/api/governance-policy", {
            **project_ref,
            "action": "create",
            "kind": "constraint",
            "statement": "Do not publish without privacy proof.",
            "effect": "block",
            "action_contains": "publish",
            "pramana": "pratyaksha",
            "confidence": 1.0,
            "provenance": {"verification_status": "verified", "source_path": "SECURITY.md", "source_hash": "privacy-policy"},
        })
        policy_id = created["policy"]["id"]

        request = urllib.request.Request(
            f"{base_url}/api/governance?db_path={db_path}&project=demo",
            headers={"X-Rta-Smriti-Token": token},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            governance = json.loads(response.read().decode("utf-8"))
        self.assertEqual([item["id"] for item in governance["policies"]], [policy_id])
        self.assertEqual(governance["receipts"], [])

        blocked = post("/api/preflight", {**project_ref, "action": "Publish release"})
        self.assertEqual(blocked["decision"], "block")
        overridden = post("/api/preflight", {
            **project_ref,
            "action": "Publish release",
            "override_reason": "Owner approved this exact publication.",
            "actor": "operator",
        })
        self.assertEqual(overridden["decision"], "allow_with_override")
        self.assertIsNotNone(overridden["override_receipt"])

        retired = post("/api/governance-policy", {
            **project_ref,
            "action": "retire",
            "policy_id": policy_id,
            "reason": "Release policy replaced.",
        })
        self.assertEqual(retired["policy"]["status"], "retired")

    def test_intelligence_workspace_and_feedback_apis_use_selected_brains(self):
        api_root = Path(self.tempdir.name) / "api"
        web_root = Path(self.tempdir.name) / "web"
        api_root.mkdir()
        web_root.mkdir()
        (api_root / "service.py").write_text(
            "def helper():\n    return 1\n\ndef run():\n    return helper()\n", encoding="utf-8",
        )
        (web_root / "README.md").write_text(
            "The web client consumes the helper envelope.\n", encoding="utf-8",
        )
        api_db = self.brain_dir / "api.sqlite"
        web_db = self.brain_dir / "web.sqlite"
        api = connect(api_db)
        try:
            init_project(api, "api", str(api_root))
            ingest_repo(api, api_root, project="api")
            memory_id = remember(
                api, "Helper changes require a focused test.", project="api",
            )["memory"]["id"]
        finally:
            api.close()
        web = connect(web_db)
        try:
            init_project(web, "web", str(web_root))
            ingest_repo(web, web_root, project="web")
        finally:
            web.close()

        started = start_console(ROOT, self.brain_dir, port=0, open_browser=False, startup_timeout=10.0)
        token = started["url"].split("#token=", 1)[1]
        base_url = f"http://127.0.0.1:{started['port']}"
        headers = {"X-Rta-Smriti-Token": token, "Content-Type": "application/json"}

        def get(path):
            request = urllib.request.Request(base_url + path, headers={"X-Rta-Smriti-Token": token})
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        def post(path, payload):
            request = urllib.request.Request(
                base_url + path,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))

        api_query = f"db_path={api_db}&project=api"
        diagnostics = get(f"/api/retrieval-diagnostics?{api_query}&query=helper")
        self.assertEqual(diagnostics["results"][0]["path"], "service.py")
        impact = get(f"/api/graph-query?{api_query}&target=helper&type=impact&depth=2")
        self.assertTrue(impact["nodes"])

        created = post("/api/workspace", {
            "db_path": str(api_db), "action": "create", "name": "product-stack",
        })
        self.assertEqual(created["workspace"]["name"], "product-stack")
        for project, member_db in (("api", api_db), ("web", web_db)):
            post("/api/workspace", {
                "db_path": str(api_db), "action": "add", "name": "product-stack",
                "project": project, "member_db_path": str(member_db),
            })
        workspace = get(
            f"/api/workspace-search?{api_query}&workspace=product-stack&query=helper&limit=4"
        )
        self.assertEqual({item["project"] for item in workspace["results"]}, {"api", "web"})

        feedback = post("/api/memory-feedback", {
            "db_path": str(api_db), "project": "api", "memory_id": memory_id,
            "outcome": "helpful", "evidence": "Operator confirmed during API test.",
        })
        self.assertEqual(feedback["outcome"], "helpful")

    def test_concurrent_starts_converge_on_one_verified_console(self):
        barrier = threading.Barrier(2)

        def launch():
            barrier.wait(timeout=5)
            return start_console(
                ROOT, self.brain_dir, port=0, open_browser=False, startup_timeout=10.0,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: launch(), range(2)))
        self.assertEqual({result["pid"] for result in results}, {results[0]["pid"]})
        self.assertEqual({result["instance_id"] for result in results}, {results[0]["instance_id"]})

    def test_dead_process_state_is_reported_as_stale_without_leaking_secret(self):
        paths = console_paths(self.brain_dir)
        write_json(
            paths["state"],
            {
                "state": "running",
                "pid": 999_999_999,
                "host": "127.0.0.1",
                "port": 8765,
            },
        )
        status = console_status(self.brain_dir)
        self.assertEqual(status["state"], "stale")
        self.assertNotIn("token", json.dumps(status).lower())

    def test_live_but_unverified_process_state_is_unresponsive(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            paths = console_paths(self.brain_dir)
            write_json(
                paths["state"],
                {
                    "state": "running",
                    "pid": os.getpid(),
                    "instance_id": "not-this-process",
                    "host": "127.0.0.1",
                    "port": int(listener.getsockname()[1]),
                },
            )
            status = console_status(self.brain_dir)
        finally:
            listener.close()
        self.assertEqual(status["state"], "unresponsive")

    def test_invalid_port_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "port"):
            start_console(ROOT, self.brain_dir, port=70_000, open_browser=False)


if __name__ == "__main__":
    unittest.main()
