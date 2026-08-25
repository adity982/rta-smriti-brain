import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CommunityHealthTests(unittest.TestCase):
    def test_readme_invites_feedback_and_first_contributions(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("### Share What Happened", readme)
        self.assertIn("/discussions/categories/q-a", readme)
        self.assertIn('label%3A%22good+first+issue%22', readme)

    def test_contributing_has_a_bounded_first_contribution_path(self):
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

        self.assertIn("## A 15-Minute First Contribution", contributing)
        self.assertIn("## Pull Request Scope", contributing)
        self.assertIn("private vulnerability reporting", contributing)

    def test_issue_router_uses_discussions_and_private_security_reporting(self):
        config = (
            ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("blank_issues_enabled: false", config)
        self.assertIn(
            "https://github.com/sulabhdubey/rta-smriti-brain/discussions/categories/q-a",
            config,
        )
        self.assertIn(
            "https://github.com/sulabhdubey/rta-smriti-brain/security/advisories/new",
            config,
        )

    def test_zed_recipe_is_linked_and_keeps_generated_config_read_only(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        usage = (ROOT / "docs" / "USAGE_GUIDE.md").read_text(encoding="utf-8")
        recipe = (ROOT / "docs" / "MCP_HOST_ZED.md").read_text(encoding="utf-8")

        self.assertIn("docs/MCP_HOST_ZED.md", readme)
        self.assertIn("MCP_HOST_ZED.md", usage)
        self.assertIn('"context_servers"', recipe)
        self.assertIn("mcp-doctor", recipe)
        self.assertIn("read-only by default", recipe)
        self.assertIn("create a new Agent task", recipe)
        self.assertIn("not an official integration or partnership", recipe)


if __name__ == "__main__":
    unittest.main()
