import json
import tomllib
import unittest
from pathlib import Path

from rta_brain import __version__

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PYTHON_VERSION = "0.9.1a1"
EXPECTED_DISPLAY_VERSION = "0.9.1-alpha"


class ReleaseMetadataTests(unittest.TestCase):
    def test_release_version_is_consistent_across_public_surfaces(self):
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
        contributors = (ROOT / "CONTRIBUTORS.md").read_text(encoding="utf-8")
        launch_site = (ROOT / "launch-site" / "src" / "main.jsx").read_text(encoding="utf-8")
        usage = (ROOT / "docs" / "USAGE_GUIDE.md").read_text(encoding="utf-8")
        release_notes = (ROOT / "docs" / "RELEASE_NOTES_v0.9.1-alpha.md").read_text(
            encoding="utf-8"
        )
        release_verification = (ROOT / "docs" / "RELEASE_VERIFICATION.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(__version__, EXPECTED_PYTHON_VERSION)
        self.assertEqual(pyproject["project"]["version"], EXPECTED_PYTHON_VERSION)
        self.assertEqual(package["version"], EXPECTED_DISPLAY_VERSION)
        self.assertEqual(package_lock["version"], EXPECTED_DISPLAY_VERSION)
        self.assertEqual(package_lock["packages"][""]["version"], EXPECTED_DISPLAY_VERSION)
        self.assertIn(f'"{EXPECTED_PYTHON_VERSION}" not in version', binary_smoke)
        self.assertIn("v0.9.1 Alpha Operator Console", dashboard)
        self.assertIn("version: 0.9.1-alpha", citation)
        self.assertIn("## Published v0.9.0-alpha", roadmap)
        self.assertIn("## Published v0.9.1-alpha", roadmap)
        self.assertIn("## [0.9.1-alpha] - 2026-08-24", changelog)
        self.assertIn("## [0.9.0-alpha] - 2026-08-23", changelog)
        self.assertIn("**Current prerelease:** [`v0.9.1-alpha`]", fact_sheet)
        self.assertIn("**Published release:**", fact_sheet)
        self.assertNotIn("Formal publication requires", fact_sheet)
        self.assertIn("/releases/tag/v0.9.1-alpha", readme)
        self.assertNotIn("uncommitted `v0.9.1-alpha`", readme)
        self.assertIn("capture           Operate the governed universal capture journal", readme)
        self.assertNotIn("uncommitted local candidate", release_notes)
        self.assertIn("13 of 13 operator-readiness", release_notes)
        self.assertIn("12 of 12 release/website code-bearing surfaces", release_notes)
        self.assertIn("## Publication Evidence", release_notes)
        self.assertIn("run 32724105024", release_notes)
        self.assertIn("downloaded without authentication", release_notes)
        self.assertIn("## Published v0.9.1-alpha Verification", release_verification)
        self.assertIn("Formal annotated tag: `v0.9.1-alpha`", release_verification)
        self.assertIn("03a9e40844a47e9a3d643c67d65e9ca701c3853125c613d3ee6b1028f12bcdb4", release_verification)
        self.assertIn("Conceived and researched by [Sulabh Dubey]", readme)
        self.assertIn("[OpenAI Codex](https://openai.com/codex/)", readme)
        self.assertIn("Rta-Smriti Brain was conceived, researched, and product-directed", contributors)
        self.assertIn("does not imply that OpenAI endorses", contributors)
        self.assertIn("Built with <a href=\"https://openai.com/codex/\">OpenAI Codex</a>", launch_site)
        self.assertIn("Conceived and researched by Sulabh Dubey", release_notes)
        self.assertNotIn("given-names: OpenAI", citation)
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
            'BASELINE_REF = "v0.9.0-alpha"',
            smoke,
        )
        self.assertIn("v0.9.0 baseline and v0.9.1 candidate", smoke)
        self.assertIn("baseline_version == expected_version", smoke)
        self.assertNotIn('"--force-reinstall", str(wheel)', smoke)


if __name__ == "__main__":
    unittest.main()
