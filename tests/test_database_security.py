import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rta_brain.db import connect, init_project, remember


class DatabaseSecurityTests(unittest.TestCase):
    def test_connect_rejects_hard_linked_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "original.sqlite"
            sqlite3.connect(original).close()
            linked = root / "linked.sqlite"
            try:
                linked.hardlink_to(original)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "unlinked regular file"):
                connect(linked)

    def test_connect_rejects_symbolic_linked_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "original.sqlite"
            sqlite3.connect(original).close()
            linked = root / "linked.sqlite"
            try:
                linked.symlink_to(original)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "linked file"):
                connect(linked)

    def test_connect_disables_trusted_schema_and_keeps_fts_working(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "brain.sqlite")
            try:
                self.assertEqual(conn.execute("PRAGMA trusted_schema").fetchone()[0], 0)
                init_project(conn, "demo", tmp)
                remember(conn, "bounded local evidence", project="demo")
                row = conn.execute("SELECT COUNT(*) FROM memory_fts").fetchone()
                self.assertEqual(row[0], 1)
            finally:
                conn.close()

    @unittest.skipIf(os.name == "nt", "POSIX mode bits are not the Windows ACL model")
    def test_connect_uses_owner_only_posix_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / "brains"
            database = brain_dir / "brain.sqlite"
            conn = connect(database)
            try:
                self.assertEqual(brain_dir.stat().st_mode & 0o777, 0o700)
                self.assertEqual(database.stat().st_mode & 0o777, 0o600)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(database) + suffix)
                    if sidecar.exists():
                        self.assertEqual(sidecar.stat().st_mode & 0o777, 0o600)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
