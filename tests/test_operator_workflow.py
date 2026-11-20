import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.blender import BlenderAdapter
from adapters.common import BLENDER
from project_config import ROOT
from tests.blender_fixtures import save_fixture_model
from workflows import operator_workflow
from workflows.jhv_workflow import apply_jhv_vbom


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
    @patch.object(operator_workflow.BlenderAdapter, "run_operator")
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
                    "transport": "blender-subprocess",
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
    @unittest.skipUnless((ROOT / "addons/jhv_dpc/jhv_dpc.py").is_file(), "Internal JHV add-on is not available")
    def test_jhv_persistent_asset_map_hits_and_invalidates(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            library = folder / "library"
            addons.mkdir(parents=True)
            library.mkdir()
            shutil.copy2(ROOT / "addons" / "jhv_dpc" / "jhv_dpc.py", addons)
            environment = os.environ.copy()
            environment.update(
                BLENDER_USER_SCRIPTS=str(scripts),
                LOCALAPPDATA=str(folder / "localappdata"),
            )
            expression = (
                "import jhv_dpc; from pathlib import Path; "
                f"jhv_dpc.thread_scan_indices([Path({str(library)!r})])"
            )

            def scan():
                completed = subprocess.run(
                    [str(BLENDER), "--background", "--python-exit-code", "1",
                     "--python-expr", expression],
                    check=True, timeout=60, capture_output=True, text=True,
                    env=environment,
                )
                return completed.stdout

            self.assertIn('"status": "MISS_REFRESH"', scan())
            self.assertIn('"status": "HIT"', scan())
            (library / "changed.blend").touch()
            invalidated = scan()
            self.assertIn('"status": "MISS_REFRESH"', invalidated)
            self.assertIn('"reason": "SOURCE_CHANGED"', invalidated)

    @unittest.skipUnless((ROOT / "addons/jhv_dpc/jhv_dpc.py").is_file(), "Internal JHV add-on is not available")
    def test_jhv_stops_before_running_operator_when_article_exists(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            model = folder / "source.blend"
            save_fixture_model(model, scene_name="AB1234")
            original = model.read_bytes()
            vbom = folder / "materials.vbom"
            vbom.write_text('<VBOM><Part name="Upper|AB1234"><VPart/></Part></VBOM>', encoding="utf-8")
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copy2(ROOT / "addons" / "jhv_dpc" / "jhv_dpc.py", addons)
            with patch.dict(os.environ, {"BLENDER_USER_SCRIPTS": str(scripts)}):
                result = apply_jhv_vbom(vbom, model, folder / "out")
            self.assertEqual(result["error_code"], "ARTICLE_ALREADY_EXISTS")
            self.assertEqual(result["details"]["article_ids"], ["AB1234"])
            self.assertEqual(list((folder / "out").rglob("result.blend")), [])
            self.assertEqual(model.read_bytes(), original)

    def test_runner_rejects_failed_poll_and_preserves_operator_error(self):
        fixture = ROOT / "tests" / "fixtures" / "ollama3d_fixture_addon"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            source_model = folder / "fixture.blend"
            save_fixture_model(source_model)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copytree(fixture, addons / fixture.name)
            adapter = BlenderAdapter()
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
