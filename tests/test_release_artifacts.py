import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_release_artifacts import assert_wheel_static_assets, referenced_static_assets


class ReleaseArtifactTests(unittest.TestCase):
    def test_wheel_assets_must_exactly_match_dashboard_index(self):
        references = referenced_static_assets()
        self.assertTrue(references)
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "candidate.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for reference in references:
                    archive.writestr(reference, b"current")
            assert_wheel_static_assets(wheel)

            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("rta_brain/static/assets/obsolete.js", b"stale")
            with self.assertRaisesRegex(RuntimeError, "stale=.*obsolete.js"):
                assert_wheel_static_assets(wheel)


if __name__ == "__main__":
    unittest.main()
