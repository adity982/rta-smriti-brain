import json
import tomllib
import unittest
from pathlib import Path

from rta_brain import __version__

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PYTHON_VERSION = "0.9.0a1"
EXPECTED_DISPLAY_VERSION = "0.9.0-alpha"


class ReleaseMetadataTests(unittest.TestCase):
    def test_candidate_version_is_consistent_across_release_surfaces(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        package_lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        binary_smoke = (ROOT / "scripts" / "smoke_binary.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "dashboard-src" / "src" / "main.jsx").read_text(encoding="utf-8")
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        fact_sheet = (ROOT / "launch-assets" / "press" / "PRODUCT_FACT_SHEET.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        usage = (ROOT / "docs" / "USAGE_GUIDE.md").read_text(encoding="utf-8")
        release_notes = (ROOT / "docs" / "RELEASE_NOTES_v0.9.0-alpha.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(__version__, EXPECTED_PYTHON_VERSION)
        self.assertEqual(pyproject["project"]["version"], EXPECTED_PYTHON_VERSION)
        self.assertEqual(package["version"], EXPECTED_DISPLAY_VERSION)
        self.assertEqual(package_lock["version"], EXPECTED_DISPLAY_VERSION)
        self.assertEqual(package_lock["packages"][""]["version"], EXPECTED_DISPLAY_VERSION)
        self.assertIn(f'"{EXPECTED_PYTHON_VERSION}" not in version', binary_smoke)
        self.assertIn("v0.9 Development Operator Console", dashboard)
        self.assertIn("version: 0.9.0-alpha", citation)
        self.assertIn("## Current v0.9.0-alpha Candidate", roadmap)
        self.assertIn("## [0.9.0-alpha] - Unreleased", changelog)
        self.assertIn("**Current candidate:** `v0.9.0-alpha`", fact_sheet)
        self.assertIn("uncommitted `v0.9.0-alpha` universal-capture candidate", readme)
        self.assertNotIn("uncommitted `v0.8.0-alpha`", readme)
        self.assertIn("capture           Operate the governed universal capture journal", readme)
        self.assertIn("uncommitted local candidate", release_notes)
        self.assertIn("fresh scan", release_notes)
        self.assertIn("zero findings", release_notes)
        self.assertIn("hosted Windows/macOS/Linux CI", release_notes)
        self.assertNotIn("post-fix candidate is required", release_notes)
        self.assertNotIn("zero Python runtime dependencies", fact_sheet)
        self.assertIn("truth             Query the bitemporal truth ledger", readme)
        self.assertIn("context           Govern and compile agent-specific context", readme)
        self.assertIn("- `brain_context_compile`", readme)
        self.assertIn("- `brain_context_explain`", readme)
        self.assertIn('--json context authority-status', usage)
        self.assertNotIn('context authority-status --json', usage)

    def test_tag_workflow_stages_the_documented_release_bundle(self):
        workflow = (ROOT / ".github" / "workflows" / "binaries.yml").read_text(encoding="utf-8")

        self.assertIn("scripts/package_release_artifacts.py", workflow)
        self.assertIn("--include-wheel", workflow)
        self.assertIn("release-artifacts/", workflow)
        self.assertIn("SHA256SUMS.txt", workflow)
        self.assertIn("pip-audit==2.10.1", workflow)
        self.assertIn("--format cyclonedx-json", workflow)
        self.assertIn("--sbom release-sbom.cdx.json", workflow)

    def test_installed_upgrade_smoke_uses_the_previous_release(self):
        smoke = (ROOT / "scripts" / "build_installed_smoke.py").read_text(encoding="utf-8")

        self.assertIn(
            'BASELINE_REF = "f8736ebaab50dba75f86e22aa246066611d2c75e"',
            smoke,
        )
        self.assertIn("v0.8 baseline and v0.9 candidate", smoke)
        self.assertIn("baseline_version == expected_version", smoke)
        self.assertNotIn('"--force-reinstall", str(wheel)', smoke)


if __name__ == "__main__":
    unittest.main()
