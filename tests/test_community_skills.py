"""Exercise progressive loading and the permission boundary with upstream and installed skills."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from platform_core.agents import community_skills as skills


OWNER = {"kind": "owner"}
NURSE = {"kind": "staff", "permissions": ["assistants", "clinical"]}


class CommunitySkillsTests(unittest.TestCase):
    def test_scheduled_skills_are_bundled_and_visible_to_the_assigned_role(self):
        care = {"kind":"staff", "permissions":["assistants", "care"]}
        self.assertIn("resident-daily-life", {s["name"] for s in skills.catalog(care)})
        self.assertNotIn("resident-health-review", {s["name"] for s in skills.catalog(care)})
        self.assertIn("resident-health-review", {s["name"] for s in skills.catalog(NURSE)})
        for name in ("resident-daily-life", "resident-health-review"):
            self.assertTrue(skills.scheduled_guidance(name))
        with self.assertRaises(ValueError):
            skills.scheduled_guidance("internal-comms")

    def test_bundled_permissions_sources_and_document_guidance(self):
        self.assertIn("resident-record-intake", {s["name"] for s in skills.catalog(OWNER)})
        self.assertNotIn("resident-record-intake", {s["name"] for s in skills.catalog(NURSE)})
        tool, = skills.tools_for(NURSE, "协助我做下这个")
        with self.assertRaises(ValueError):
            tool.execute({"name": "resident-record-intake"})
        guide = tool.execute({"name": "internal-comms"})
        self.assertIn("examples/faq-answers.md", guide["references"])
        example = tool.execute({"name": "internal-comms", "reference": "examples/faq-answers.md"})
        self.assertIn("FAQ", example["instructions"])
        self.assertIn("前导零", skills.document_guidance(NURSE))
        for actor in (None, {"kind": "staff", "permissions": []}, {"kind": "family", "permissions": ["assistants"]}):
            self.assertFalse(skills.document_guidance(actor))
            self.assertEqual(skills.tools_for(actor), ())

    def test_installed_skill_only_loads_selected_markdown(self):
        with TemporaryDirectory() as temp, patch.dict("os.environ", {"NH_AGENT_SKILL_DIRS": temp}):
            package = Path(temp) / "shift-check"
            docs = package / "references"
            docs.mkdir(parents=True)
            guide = package / "SKILL.md"
            guide.write_text("---\nname: shift-check\ndescription: >\n  Shift handoff\n  evidence\n---\nBody only after selection.\n", encoding="utf-8")
            (docs / "notes.md").write_text("Read only this checklist.", encoding="utf-8")
            (docs / "script.sh").write_text("exit 1")
            (docs / "outside.md").symlink_to(guide)
            catalog = skills.catalog(NURSE)
            self.assertIn({"name": "shift-check", "description": "Shift handoff evidence"}, catalog)
            tool, = skills.tools_for(NURSE)
            definition = tool.function()["function"]
            self.assertIn("shift-check", definition["parameters"]["properties"]["name"]["enum"])
            self.assertNotIn("Body only", definition["description"])
            selected = tool.execute({"name": "shift-check"})
            self.assertEqual(selected["instructions"], "Body only after selection.")
            self.assertEqual(selected["references"], ["references/notes.md"])
            self.assertEqual(tool.execute({"name": "shift-check", "reference": "references/notes.md"})["instructions"], "Read only this checklist.")
            for path in ("../SKILL.md", "/etc/passwd", "references/script.sh", "references/outside.md", None):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    tool.execute({"name": "shift-check", "reference": path})
            guide.write_text("---\nname: shift-check\ndescription: Revised instructions\nmetadata:\n  workspace-permission: finance\n---\nRestricted contents")
            with self.assertRaises(ValueError):
                tool.execute({"name": "shift-check"})
            self.assertNotIn("shift-check", {s["name"] for s in skills.catalog(NURSE)})

    def test_malformed_oversize_symlink_packages_fail_closed(self):
        with TemporaryDirectory() as temp, patch.dict("os.environ", {"NH_AGENT_SKILL_DIRS": temp}):
            root = Path(temp)
            for name, header in (("not-a-map", "[]"), ("wrong-name", "name: other\ndescription: nope"),
                                 ("too-big", "x" * skills.MAX_FILE), ("tagged", "!!python/name:os.getcwd ''")):
                folder = root / name
                folder.mkdir()
                (folder / "SKILL.md").write_text("---\n" + header + "\n---\nnope")
            (root / "link").symlink_to(skills.BUNDLED / "xlsx", target_is_directory=True)
            with self.assertLogs(skills.logger, level="WARNING"):
                names = {item["name"] for item in skills.catalog(OWNER)}
            self.assertFalse(names & {"not-a-map", "wrong-name", "too-big", "tagged", "link"})
