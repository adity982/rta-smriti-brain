import tempfile
import unittest
from pathlib import Path

from rta_brain.autostart import autostart_status, disable_autostart, enable_autostart


ROOT = Path(__file__).resolve().parents[1]


class AutostartTests(unittest.TestCase):
    def test_windows_startup_entry_is_reversible_and_never_opens_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            appdata = Path(tmp) / "AppData" / "Roaming"
            brain_dir = Path(tmp) / "brains with spaces"
            enabled = enable_autostart(
                ROOT, brain_dir, platform_name="win32", home=home,
                environment={"APPDATA": str(appdata)},
            )
            entry = Path(enabled["entry_path"])
            self.assertTrue(entry.is_file())
            text = entry.read_text(encoding="utf-8")
            self.assertIn("console start", text)
            self.assertIn("--no-open", text)
            self.assertIn(str(brain_dir), text)
            self.assertTrue(autostart_status(brain_dir, platform_name="win32", home=home, environment={"APPDATA": str(appdata)})["enabled"])
            disabled = disable_autostart(brain_dir, platform_name="win32", home=home, environment={"APPDATA": str(appdata)})
            self.assertFalse(disabled["enabled"])
            self.assertFalse(entry.exists())

    def test_macos_launch_agent_uses_program_arguments_without_a_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            brain_dir = home / "brains & memory"
            payload = enable_autostart(ROOT, brain_dir, platform_name="darwin", home=home, environment={})
            text = Path(payload["entry_path"]).read_text(encoding="utf-8")
            self.assertIn("<key>ProgramArguments</key>", text)
            self.assertIn("<string>--no-open</string>", text)
            self.assertIn("brains &amp; memory", text)
            self.assertNotIn("<key>Shell", text)

    def test_linux_desktop_entry_is_generated_only_for_supported_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            brain_dir = home / "brains"
            supported = enable_autostart(
                ROOT, brain_dir, platform_name="linux", home=home,
                environment={"DISPLAY": ":0", "XDG_CONFIG_HOME": str(home / ".config")},
            )
            text = Path(supported["entry_path"]).read_text(encoding="utf-8")
            self.assertIn("Type=Application", text)
            self.assertIn("--no-open", text)

            unsupported = autostart_status(
                brain_dir, platform_name="linux", home=home,
                environment={"WSL_DISTRO_NAME": "Ubuntu"},
            )
            self.assertFalse(unsupported["supported"])
            self.assertEqual(unsupported["reason"], "wsl")

    def test_linked_autostart_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            appdata = Path(tmp) / "AppData" / "Roaming"
            brain_dir = Path(tmp) / "brains"
            first = enable_autostart(
                ROOT, brain_dir, platform_name="win32", home=home,
                environment={"APPDATA": str(appdata)},
            )
            entry = Path(first["entry_path"])
            entry.unlink()
            victim = Path(tmp) / "victim.cmd"
            victim.write_text("keep\n", encoding="utf-8")
            entry.hardlink_to(victim)
            with self.assertRaisesRegex(ValueError, "linked autostart entry"):
                enable_autostart(
                    ROOT, brain_dir, platform_name="win32", home=home,
                    environment={"APPDATA": str(appdata)},
                )
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
