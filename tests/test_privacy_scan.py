import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rta_brain.privacy import find_sensitive_text
from scripts.privacy_scan import scan


class PrivacyScanTests(unittest.TestCase):
    def test_privacy_scan_runs_as_a_direct_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parents[1] / "scripts" / "privacy_scan.py"), "--root", str(root)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_detector_covers_release_secret_and_generic_path_patterns(self):
        values = {
            "aws-access-key": "AK" + "IA" + "Q" * 16,
            "private-key": "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nfixture",
            "jwt": ".".join(("eyJ" + "a" * 12, "b" * 12, "c" * 12)),
            "unc-path": "\\\\server\\share\\private\\file.txt",
            "windows-absolute-path": "D:" + "\\private\\workspace\\file.txt",
            "posix-absolute-path": "/" + "/".join(("srv", "private", "workspace", "file.txt")),
        }
        findings = find_sensitive_text("\n".join(values.values()))
        labels = {finding.label for finding in findings}
        self.assertTrue(set(values).issubset(labels))

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

    def test_privacy_module_is_not_exempt_from_user_path_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            module = root / "rta_brain" / "privacy.py"
            module.parent.mkdir()
            private_path = "C:" + r"\Users\Private User\project\proof.txt"
            module.write_text(f'LEAKED_FIXTURE = r"{private_path}"\n', encoding="utf-8")

            self.assertIn(("rta_brain/privacy.py", "windows-user-path"), scan(root, []))

    def test_known_detector_definition_lines_are_narrowly_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            source_root = Path(__file__).parents[1]
            scanner = root / "scripts" / "privacy_scan.py"
            scanner.parent.mkdir()
            scanner_line = next(
                line for line in (source_root / "scripts" / "privacy_scan.py").read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("prefixes.extend")
            )
            scanner.write_text(scanner_line + "\n", encoding="utf-8")
            detector = root / "rta_brain" / "privacy.py"
            detector.parent.mkdir()
            detector_line = next(
                line for line in (source_root / "rta_brain" / "privacy.py").read_text(encoding="utf-8").splitlines()
                if line.strip().startswith('"unc-path"')
            )
            detector.write_text(detector_line + "\n", encoding="utf-8")

            self.assertEqual(scan(root, []), [])


if __name__ == "__main__":
    unittest.main()
