import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.blender_mcp import BlenderMcpAdapter
from adapters.common import BLENDER, REGISTRY
from project_config import ROOT
from workflows import operator_workflow


GENERIC_CAPABILITY = {
    "id": "blender.fixture.run",
    "provider": "blender_operator",
    "handler": "generic_operator",
    "target": "fixture.run",
    "addon_module": "fixture_addon",
    "risk": "mutating",
    "expose": "generic",
    "enabled": True,
    "params": {
        "type": "object",
        "properties": {"count": {"type": "integer", "minimum": 1}},
        "required": ["count"],
        "additionalProperties": False,
    },
}


class OperatorWorkflowTests(unittest.TestCase):
    @patch.object(operator_workflow, "log")
    @patch.object(operator_workflow.BlenderMcpAdapter, "run_operator")
    @patch.object(operator_workflow.REGISTRY, "require")
    @patch.object(operator_workflow, "scoped_path")
    def test_operator_workflow_writes_verification(
        self, scoped, require, run_operator, _log
    ):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            model = folder / "input.blend"
            output = folder / "outputs"
            model.write_bytes(b"blend")
            scoped.side_effect = [model, output]
            require.return_value = GENERIC_CAPABILITY

            def result(_capability, _params, _model, output_path, report_path, run_id):
                Path(output_path).write_bytes(b"result")
                Path(report_path).write_text("{}", encoding="utf-8")
                return {
                    "ok": True,
                    "producer": "ollama3d-generic-operator",
                    "run_id": run_id,
                    "operator": "fixture.run",
                    "diff": {},
                    "output_sha256": "adapter-verified",
                    "verified_after_reopen": True,
                    "transport": "official-blender-mcp",
                }

            run_operator.side_effect = result
            state = operator_workflow.run_blender_operator(
                "blender.fixture.run", {"count": 2}, model, output
            )
            self.assertEqual(state["status"], "completed")
            self.assertTrue(Path(state["output_path"]).is_file())
            self.assertTrue(Path(state["evidence"]["verification"]).is_file())

    @patch.object(operator_workflow, "log")
    @patch.object(operator_workflow.REGISTRY, "require")
    @patch.object(operator_workflow, "scoped_path")
    def test_validation_and_disabled_errors_are_structured(
        self, scoped, require, _log
    ):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            model = folder / "input.blend"
            model.write_bytes(b"blend")
            scoped.side_effect = [model, folder / "bad-params"]
            require.return_value = GENERIC_CAPABILITY
            invalid = operator_workflow.run_blender_operator(
                "blender.fixture.run", {"count": True}, model, folder / "bad-params"
            )
            self.assertEqual(invalid["error_code"], "PARAMS_INVALID")

            scoped.side_effect = [model, folder / "disabled"]
            require.side_effect = RuntimeError("Capability is disabled")
            disabled = operator_workflow.run_blender_operator(
                "blender.fixture.run", {"count": 2}, model, folder / "disabled"
            )
            self.assertEqual(disabled["error_code"], "CAPABILITY_DISABLED")


@unittest.skipUnless(BLENDER.is_file(), "Configured Blender executable is unavailable")
class BlenderOperatorRegressionTests(unittest.TestCase):
    @staticmethod
    def _inspect(adapter, model_path, directory, label):
        code = (
            "import bpy\n"
            "result = {name: {"
            "'material': bpy.data.objects[name].active_material.name, "
            "'color_hex': bpy.data.objects[name].get('bom_color_hex'), "
            "'diffuse_color': [round(value, 6) for value in "
            "bpy.data.objects[name].active_material.diffuse_color]} "
            "for name in ('Upper', 'Sole', 'Laces')}"
        )
        return adapter._execute(
            code,
            directory / f"inspect-{label}.log",
            model_path=model_path,
            timeout=60,
        )

    def test_generic_apply_vbom_matches_legacy_path_after_reopen(self):
        capability = REGISTRY.require(
            "blender.ollama3d_proof.apply_vbom", provider="blender_operator"
        )
        source_model = ROOT / "inputs" / "Sneaker_Unassigned.blend"
        vbom = ROOT / "tests" / "fixtures" / "proof_v1.vbom.xml"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            adapter = BlenderMcpAdapter()
            generic_output = folder / "generic.blend"
            generic_report = folder / "generic-report.json"
            generic = adapter.run_operator(
                capability,
                {"filepath": str(vbom), "run_id": "TEST-RUN"},
                source_model,
                generic_output,
                generic_report,
                "TEST-RUN",
            )
            legacy_output = folder / "legacy.blend"
            legacy_report = folder / "legacy-report.json"
            adapter.apply(
                vbom,
                source_model,
                legacy_output,
                legacy_report,
                "TEST-RUN",
            )
            generic_scene = self._inspect(adapter, generic_output, folder, "generic")
            legacy_scene = self._inspect(adapter, legacy_output, folder, "legacy")

        self.assertTrue(generic["verified_after_reopen"])
        self.assertEqual(generic_scene, legacy_scene)
        self.assertEqual(
            {value["color_hex"] for value in generic_scene.values()},
            {"#3366CC", "#EEEEEE", "#CC3333"},
        )
        self.assertEqual(
            {value["material"] for value in generic_scene.values()},
            {"Fixture Upper", "Fixture Sole", "Fixture Laces"},
        )
        self.assertEqual(
            set(generic["diff"]["objects"]["changed"]),
            {"Upper", "Sole", "Laces"},
        )

    @patch.object(operator_workflow, "log")
    def test_exposed_registry_capability_runs_through_workflow(self, _log):
        source_model = ROOT / "inputs" / "Sneaker_Unassigned.blend"
        vbom = ROOT / "tests" / "fixtures" / "proof_v1.vbom.xml"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            state = operator_workflow.run_blender_operator(
                "blender.ollama3d_proof.apply_vbom",
                {"filepath": str(vbom), "run_id": "TEST-RUN"},
                source_model,
                folder,
            )
            self.assertEqual(state["status"], "completed")
            self.assertTrue(Path(state["output_path"]).is_file())
            self.assertTrue(Path(state["evidence"]["verification"]).is_file())

    def test_runner_rejects_failed_poll_and_preserves_operator_error(self):
        fixture = ROOT / "tests" / "fixtures" / "ollama3d_fixture_addon"
        proof_addon = ROOT / "blender" / "ollama3d_proof_addon"
        source_model = ROOT / "inputs" / "Sneaker_Unassigned.blend"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copytree(fixture, addons / fixture.name)
            shutil.copytree(proof_addon, addons / proof_addon.name)
            adapter = BlenderMcpAdapter()
            capability = {
                "addon_module": "ollama3d_fixture_addon",
                "target": "ollama3d_fixture.poll_false",
            }
            with patch.dict(os.environ, {"BLENDER_USER_SCRIPTS": str(scripts)}):
                capability["target"] = "ollama3d_fixture.all_types"
                with self.assertRaisesRegex(RuntimeError, "count.*wrong type"):
                    adapter.run_operator(
                        capability,
                        {"count": True},
                        source_model,
                        folder / "type.blend",
                        folder / "type.json",
                        "TYPE-RUN",
                    )
                capability["target"] = "ollama3d_fixture.poll_false"
                with self.assertRaisesRegex(RuntimeError, "poll failed"):
                    adapter.run_operator(
                        capability,
                        {},
                        source_model,
                        folder / "poll.blend",
                        folder / "poll.json",
                        "POLL-RUN",
                    )
                capability["target"] = "ollama3d_fixture.cancelled"
                with self.assertRaisesRegex(RuntimeError, "fixture cancellation"):
                    adapter.run_operator(
                        capability,
                        {},
                        source_model,
                        folder / "cancelled.blend",
                        folder / "cancelled.json",
                        "CANCELLED-RUN",
                    )


if __name__ == "__main__":
    unittest.main()
