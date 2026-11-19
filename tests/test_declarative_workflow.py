import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.common import BLENDER
from capability_registry import CapabilityRegistry
from project_config import ROOT
from workflow_definitions import interpolate_definition, load_definition, validate_definition
from workflows import blender_workflow


def fixture_registry():
    return CapabilityRegistry(
        ROOT / "tests" / "fixture-capabilities.json",
        {
            "schema_version": 1,
            "capabilities": [
                {
                    "id": "blender.fixture.all_types",
                    "provider": "blender_operator",
                    "handler": "generic_operator",
                    "target": "ollama3d_fixture.all_types",
                    "addon_module": "ollama3d_fixture_addon",
                    "risk": "mutating",
                    "params": {
                        "type": "object",
                        "properties": {
                            "count": {"type": "integer", "minimum": 1, "maximum": 8},
                            "title": {"type": "string"},
                            "mode": {"type": "string", "enum": ["ONE", "TWO"]},
                        },
                        "required": [],
                        "additionalProperties": False,
                    },
                    "enabled": True,
                }
            ],
        },
    )


class WorkflowDefinitionTests(unittest.TestCase):
    def test_fixture_definition_interpolates_only_exact_input_references(self):
        definition = load_definition(
            ROOT / "workflows" / "definitions", "workflow.fixture_generic"
        )
        resolved = interpolate_definition(
            definition,
            {
                "model_path": "E:/model.blend",
                "output_dir": "E:/outputs",
                "article_name": "Samba",
            },
        )
        self.assertEqual(resolved["steps"][0]["params"]["title"], "Samba")

        invalid = dict(definition)
        invalid["steps"] = [
            {
                "id": "bad",
                "capability": "blender.fixture.all_types",
                "params": {"title": "prefix-${inputs.article_name}"},
            }
        ]
        with self.assertRaisesRegex(ValueError, "Only exact"):
            validate_definition(invalid)

    def test_unknown_inputs_and_postconditions_are_rejected(self):
        definition = load_definition(
            ROOT / "workflows" / "definitions", "workflow.fixture_generic"
        )
        with self.assertRaisesRegex(ValueError, "inputs do not match"):
            interpolate_definition(definition, {"model_path": "x"})
        invalid = dict(definition)
        invalid["postconditions"] = [{"type": "python_expression"}]
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            validate_definition(invalid)


@unittest.skipUnless(BLENDER.is_file(), "Configured Blender executable is unavailable")
class DeclarativeWorkflowBlenderTests(unittest.TestCase):
    @patch.object(blender_workflow, "log")
    def test_two_fixture_steps_run_in_one_verified_blender_session(self, _log):
        fixture = ROOT / "tests" / "fixtures" / "ollama3d_fixture_addon"
        proof_addon = ROOT / "blender" / "ollama3d_proof_addon"
        model = ROOT / "inputs" / "Sneaker_Unassigned.blend"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copytree(fixture, addons / fixture.name)
            shutil.copytree(proof_addon, addons / proof_addon.name)
            output = folder / "outputs"
            with patch.dict(os.environ, {"BLENDER_USER_SCRIPTS": str(scripts)}), patch.object(
                blender_workflow, "REGISTRY", fixture_registry()
            ):
                state = blender_workflow.run_blender_workflow(
                    "workflow.fixture_generic",
                    {
                        "model_path": str(model),
                        "output_dir": str(output),
                        "article_name": "Samba",
                    },
                )
                output_exists = Path(state["output_path"]).is_file()
        self.assertEqual(state["status"], "completed")
        self.assertEqual([step["id"] for step in state["steps"]], ["inspect_article", "confirm_article"])
        self.assertTrue(state["output_path"].endswith("result.blend"))
        self.assertTrue(output_exists)


if __name__ == "__main__":
    unittest.main()
