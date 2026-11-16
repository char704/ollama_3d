"""Tool library manifest discovery and validation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_config import load
from tool_registry import load_catalog


class ToolRegistryTests(unittest.TestCase):
    def test_project_catalog_contains_expected_blender_tools(self):
        config = load()
        ids = {item["id"] for item in config["_tool_catalog"]["tools"]}
        self.assertIn("add_cube", ids)
        self.assertIn("start_rhino_server", ids)
        self.assertEqual(ids, {item["id"] for item in config["blender_operators"]})

    def test_duplicate_ids_are_rejected_across_files(self):
        manifest = {
            "schema_version": 1,
            "id": "duplicate_tool",
            "name": "Duplicate",
            "description": "Test duplicate detection.",
            "executor": "python",
            "enabled": True,
        }
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            library = root / "tools"
            library.mkdir()
            for name in ("one.json", "two.json"):
                (library / name).write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicated id"):
                load_catalog(root, {"directory": "tools"})

    def test_library_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "inside the project"):
                load_catalog(folder, {"directory": "../elsewhere"})


if __name__ == "__main__":
    unittest.main()
