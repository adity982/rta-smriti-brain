import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from rta_brain.console_daemon import (
    console_paths,
    console_status,
    open_console,
    restart_console,
    start_console,
    stop_console,
)
from rta_brain.runtime_control import (
    detached_process_kwargs,
    process_alive,
    read_json,
    write_json,
)


ROOT = Path(__file__).resolve().parents[1]


class RuntimeControlTests(unittest.TestCase):
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
        else:
            self.assertTrue(options["start_new_session"])
            self.assertNotIn("creationflags", options)


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
