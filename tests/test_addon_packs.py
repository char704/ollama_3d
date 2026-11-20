import json
import os
import shutil
import tempfile
import unittest
from tests.blender_fixtures import save_fixture_model
from pathlib import Path
from unittest.mock import patch

import manage
from adapters.common import BLENDER, CONFIG
from capability_registry import load_registry
from project_config import ROOT
from workflows import operator_workflow


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class AddonPackTests(unittest.TestCase):
    def test_registry_hot_reloads_enabled_state_and_pack_workflows(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            addons = folder / "addons"
            pack = addons / "fixture_addon"
            document = {
                "module": "fixture_addon",
                "description": "Fixture pack",
                "operators": {
                    "fixture.run": {
                        "enabled": False,
                        "risk": "mutating",
                        "description": "Run fixture",
                        "params": {"type": "object", "properties": {}, "required": []},
                    }
                },
            }
            write_json(pack / "addon.json", document)
            write_json(
                pack / "workflows" / "workflow.pack_one.json",
                {
                    "id": "workflow.pack_one",
                    "version": "1.0.0",
                    "inputs": {"model_path": "path", "output_dir": "path"},
                    "steps": [
                        {"id": "run", "capability": "blender.fixture_addon.run", "params": {}}
                    ],
                    "postconditions": [],
                },
            )
            registry = load_registry(
                ROOT / "capabilities.json",
                addon_root=addons,
                workflow_root=folder / "core-workflows",
            )
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                registry.require("blender.fixture_addon.run")
            self.assertEqual(registry.require_workflow("workflow.pack_one")["version"], "1.0.0")

            document["operators"]["fixture.run"]["enabled"] = True
            write_json(pack / "addon.json", document)
            self.assertEqual(
                registry.require("blender.fixture_addon.run")["target"], "fixture.run"
            )
            self.assertEqual(
                [item["id"] for item in registry.generic_capabilities()],
                ["blender.fixture_addon.run"],
            )
            (pack / "docs.md").write_text("# Live docs", encoding="utf-8")
            self.assertEqual(
                registry.require("blender.fixture_addon.run")["docs"],
                "addons/fixture_addon/docs.md",
            )

    def test_pack_docs_cannot_escape_and_duplicate_ids_are_clear(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            base = folder / "capabilities.json"
            write_json(
                base,
                {
                    "schema_version": 1,
                    "capabilities": [
                        {
                            "id": "blender.fixture_addon.run",
                            "provider": "blender_builtin",
                            "handler": "run",
                            "target": "fixture.run",
                            "enabled": True,
                        }
                    ],
                },
            )
            pack = folder / "addons" / "fixture_addon"
            outside = folder / "outside.md"
            outside.write_text("private", encoding="utf-8")
            document = {
                "module": "fixture_addon",
                "description": "Fixture pack",
                "operators": {
                    "fixture.run": {
                        "enabled": True,
                        "risk": "read",
                        "description": "Run",
                        "docs": "../../outside.md",
                        "params": {"type": "object", "properties": {}},
                    }
                },
            }
            write_json(pack / "addon.json", document)
            with self.assertRaisesRegex(ValueError, "docs must stay"):
                load_registry(base)
            document["operators"]["fixture.run"].pop("docs")
            write_json(pack / "addon.json", document)
            with self.assertRaisesRegex(ValueError, "duplicate id"):
                load_registry(base)


@unittest.skipUnless(BLENDER.is_file(), "Configured Blender executable is unavailable")
class AddonPackAcceptanceTests(unittest.TestCase):
    @patch.object(operator_workflow, "log")
    def test_add_enable_and_run_fixture_without_python_changes(self, _log):
        fixture = ROOT / "tests" / "fixtures" / "ollama3d_fixture_addon"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            model = folder / "fixture.blend"
            save_fixture_model(model)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copytree(fixture, addons / fixture.name)
            with patch.dict(os.environ, {"BLENDER_USER_SCRIPTS": str(scripts)}):
                manage.addon_add(CONFIG, fixture.name, root=folder)
                pack_path = folder / "addons" / fixture.name / "addon.json"
                added = json.loads(pack_path.read_text(encoding="utf-8"))
                self.assertTrue(
                    all(not item["enabled"] for item in added["operators"].values())
                )
                manage.addon_set_enabled(
                    fixture.name, ["ollama3d_fixture.all_types"], True, root=folder
                )
                registry = load_registry(
                    ROOT / "capabilities.json",
                    addon_root=folder / "addons",
                    workflow_root=ROOT / "workflows" / "definitions",
                )
                capability_id = "blender.ollama3d_fixture_addon.all_types"
                self.assertTrue(registry.require(capability_id)["enabled"])
                output = folder / "outputs"
                with patch.object(operator_workflow, "REGISTRY", registry):
                    state = operator_workflow.run_blender_operator(
                        capability_id,
                        {"count": 2},
                        model,
                        output,
                    )
                self.assertEqual(state["status"], "completed")
                self.assertTrue(Path(state["output_path"]).is_file())
                self.assertEqual(list((folder / "addons").rglob("*.py")), [])


if __name__ == "__main__":
    unittest.main()
