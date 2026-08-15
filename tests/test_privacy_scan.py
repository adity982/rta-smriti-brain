import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.privacy_scan import scan


class PrivacyScanTests(unittest.TestCase):
    def test_detects_user_path_in_command_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            private_path = "C:" + r"\Users\Private User\project\run.py"
            (root / "launch.cmd").write_text(f'python "{private_path}"', encoding="utf-8")
            self.assertIn(("launch.cmd", "windows-user-path"), scan(root, []))

    def test_detects_utf16_path_in_media_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            metadata = ("C:" + r"\Users\Sulabh Kumar\Videos\launch.mp4").encode("utf-16-le")
            (root / "poster.png").write_bytes(b"PNG" + metadata)
            self.assertIn(("poster.png", "windows-user-path"), scan(root, []))


if __name__ == "__main__":
    unittest.main()
