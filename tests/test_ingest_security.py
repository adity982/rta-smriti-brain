import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain.ingest import build_file_record, read_text


class SecureIngestionTests(unittest.TestCase):
    def test_read_text_uses_the_verified_descriptor_instead_of_path_read_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")

            with patch.object(Path, "read_text", side_effect=AssertionError("unsafe reopen")):
                self.assertEqual(read_text(source, root=root), "VALUE = 1\n")

    def test_read_text_rejects_a_regular_file_replaced_during_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.py"
            replacement = root / "replacement.py"
            source.write_text("SAFE = True\n", encoding="utf-8")
            replacement.write_text("REPLACED = True\n", encoding="utf-8")
            original_open = os.open
            replaced = False

            def swap_then_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal replaced
                if not replaced and Path(path).name == source.name:
                    replaced = True
                    os.replace(replacement, source)
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with patch("rta_brain.ingest.os.open", side_effect=swap_then_open):
                self.assertIsNone(read_text(source, root=root))

    def test_read_text_rejects_an_oversized_file_replaced_during_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.py"
            replacement = root / "replacement.py"
            source.write_text("small\n", encoding="utf-8")
            replacement.write_text("X" * 513, encoding="utf-8")
            original_open = os.open
            replaced = False

            def swap_then_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal replaced
                if not replaced and Path(path).name == source.name:
                    replaced = True
                    os.replace(replacement, source)
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with patch("rta_brain.ingest.os.open", side_effect=swap_then_open):
                self.assertIsNone(read_text(source, max_bytes=512, root=root))

    def test_read_text_rejects_hard_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.py"
            outside.write_text("SECRET = True\n", encoding="utf-8")
            hard_link = root / "hard.py"
            os.link(outside, hard_link)
            self.assertIsNone(read_text(hard_link, root=root))

    def test_read_text_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.py"
            outside.write_text("SECRET = True\n", encoding="utf-8")
            symbolic_link = root / "symbolic.py"
            try:
                symbolic_link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            self.assertIsNone(read_text(symbolic_link, root=root))

    def test_build_file_record_rejects_paths_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "repo"
            root.mkdir()
            outside = base / "outside.py"
            outside.write_text("SECRET = True\n", encoding="utf-8")
            self.assertIsNone(build_file_record(root, outside))

    def test_repeated_atomic_replacement_never_returns_torn_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.py"
            values = {"A" * 4096, "B" * 4096}
            source.write_text(next(iter(values)), encoding="utf-8")
            stop = threading.Event()

            def replace_repeatedly():
                index = 0
                while not stop.is_set():
                    pending = root / f"pending-{index % 2}.py"
                    pending.write_text(("A" if index % 2 else "B") * 4096, encoding="utf-8")
                    try:
                        os.replace(pending, source)
                        index += 1
                    except PermissionError:
                        pending.unlink(missing_ok=True)

            writer = threading.Thread(target=replace_repeatedly, daemon=True)
            writer.start()
            try:
                observed = [read_text(source, max_bytes=8192, root=root) for _ in range(300)]
            finally:
                stop.set()
                writer.join(timeout=2)

            self.assertTrue(all(value is None or value in values for value in observed))


if __name__ == "__main__":
    unittest.main()
