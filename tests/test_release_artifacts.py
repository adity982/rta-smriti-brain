import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_release_artifacts import assert_wheel_static_assets, referenced_static_assets, stage_sbom


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

    def test_sbom_must_be_bounded_unlinked_cyclonedx_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            output.mkdir()
            sbom = root / "candidate.cdx.json"
            sbom.write_text('{"bomFormat":"CycloneDX","specVersion":"1.6"}', encoding="utf-8")

            staged = stage_sbom(sbom, output, version="0.9.0a1")
            self.assertTrue(staged.name.startswith("rta-smriti-brain-0.9.0a1-"))
            self.assertEqual(staged.read_bytes(), sbom.read_bytes())

            invalid = root / "invalid.json"
            invalid.write_text('{"bomFormat":"SPDX"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CycloneDX"):
                stage_sbom(invalid, output, version="0.9.0a1")

            linked = root / "linked.cdx.json"
            linked.hardlink_to(sbom)
            with self.assertRaisesRegex(ValueError, "hard linked"):
                stage_sbom(linked, output, version="0.9.0a1")

            symbolic = root / "symbolic.cdx.json"
            try:
                symbolic.symlink_to(sbom)
            except OSError:
                pass
            else:
                with self.assertRaises(FileNotFoundError):
                    stage_sbom(symbolic, output, version="0.9.0a1")



if __name__ == "__main__":
    unittest.main()
