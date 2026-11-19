import os
import json
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from adapters.blender_mcp import BlenderMcpAdapter
from adapters.common import BLENDER
from capability_discovery import propose_entries, to_schema, validate_params
from capability_registry import CapabilityRegistry
from project_config import ROOT, load


SAMPLE_OPERATOR = {
    "addon_module": "fixture_addon",
    "bl_idname": "fixture.all_types",
    "bl_label": "All types",
    "bl_description": "Fixture operator",
    "poll_default": True,
    "params": [
        {"identifier": "flag", "type": "BOOLEAN", "is_required": True, "array_length": 0},
        {
            "identifier": "count",
            "type": "INT",
            "is_required": True,
            "array_length": 0,
            "hard_min": 1,
            "hard_max": 5,
        },
        {
            "identifier": "mode",
            "type": "ENUM",
            "is_required": False,
            "array_length": 0,
            "enum": ["ONE", "TWO"],
        },
        {
            "identifier": "filepath",
            "type": "STRING",
            "subtype": "FILE_PATH",
            "is_required": True,
            "array_length": 0,
        },
        {
            "identifier": "vector",
            "type": "FLOAT",
            "is_required": False,
            "array_length": 3,
        },
        {
            "identifier": "pointer",
            "type": "POINTER",
            "supported": False,
            "is_required": False,
            "array_length": 0,
        },
    ],
}


class DiscoveryUnitTests(unittest.TestCase):
    def setUp(self):
        self.config = load()
        self.schema = to_schema(SAMPLE_OPERATOR)

    def test_to_schema_maps_arrays_paths_and_unsupported_properties(self):
        self.assertEqual(self.schema["properties"]["count"]["type"], "integer")
        self.assertEqual(self.schema["properties"]["vector"]["type"], "array")
        self.assertTrue(self.schema["properties"]["filepath"]["x-path"])
        self.assertEqual(self.schema["unsupported"], ["pointer"])

    def test_validate_params_normalizes_paths_and_rejects_invalid_values(self):
        valid = validate_params(
            self.schema,
            {
                "flag": True,
                "count": 2,
                "mode": "ONE",
                "filepath": "inputs/Footwear_BOM.xlsx",
                "vector": [1, 2.0, 3],
            },
            self.config,
        )
        self.assertTrue(Path(valid["filepath"]).is_absolute())
        with self.assertRaisesRegex(ValueError, "count.*integer"):
            validate_params(
                self.schema,
                {"flag": True, "count": True, "filepath": "inputs/Footwear_BOM.xlsx"},
                self.config,
            )
        with self.assertRaisesRegex(ValueError, "mode"):
            validate_params(
                self.schema,
                {"flag": True, "count": 2, "mode": "THREE", "filepath": "inputs/Footwear_BOM.xlsx"},
                self.config,
            )
        with self.assertRaisesRegex(ValueError, "scope"):
            validate_params(
                self.schema,
                {"flag": True, "count": 2, "filepath": "C:/Windows/win.ini"},
                self.config,
            )

    def test_proposals_are_disabled_and_skip_registered_targets(self):
        registry = CapabilityRegistry(
            ROOT / "test-capabilities.json",
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "id": "system.status",
                        "provider": "system",
                        "handler": "status",
                        "target": "local.readiness",
                        "enabled": True,
                    },
                    {
                        "id": "blender.fixture.existing",
                        "provider": "blender_builtin",
                        "handler": "existing",
                        "target": "fixture.existing",
                        "enabled": True,
                    },
                ],
            },
        )
        existing = deepcopy(SAMPLE_OPERATOR)
        existing["bl_idname"] = "fixture.existing"
        proposals = propose_entries({"operators": [SAMPLE_OPERATOR, existing]}, registry)
        self.assertEqual(len(proposals), 1)
        self.assertFalse(proposals[0]["enabled"])
        self.assertEqual(proposals[0]["risk"], "filesystem")
        self.assertEqual(proposals[0]["target"], "fixture.all_types")


@unittest.skipUnless(BLENDER.is_file(), "Configured Blender executable is unavailable")
class BlenderDiscoveryTests(unittest.TestCase):
    def test_fixture_addon_rna_is_discovered(self):
        fixture = ROOT / "tests" / "fixtures" / "ollama3d_fixture_addon"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copytree(fixture, addons / fixture.name)
            with patch.dict(os.environ, {"BLENDER_USER_SCRIPTS": str(scripts)}):
                report = BlenderMcpAdapter().discover(
                    ["ollama3d_fixture_addon"], folder / "report"
                )
        operators = {item["bl_idname"]: item for item in report["operators"]}
        self.assertTrue(
            {
                "ollama3d_fixture.all_types",
                "ollama3d_fixture.poll_false",
                "ollama3d_fixture.cancelled",
                "ollama3d_fixture.pointer",
                "ollama3d_fixture.internal",
            }.issubset(operators)
        )
        self.assertFalse(operators["ollama3d_fixture.poll_false"]["poll_default"])
        params = {
            item["identifier"]: item
            for item in operators["ollama3d_fixture.pointer"]["params"]
        }
        self.assertFalse(params["value"]["supported"])
        all_types = {
            item["identifier"]: item
            for item in operators["ollama3d_fixture.all_types"]["params"]
        }
        self.assertEqual(all_types["count"]["type"], "INT")
        self.assertEqual(all_types["mode"]["type"], "ENUM")
        self.assertEqual(all_types["filepath"]["subtype"], "FILE_PATH")
        self.assertTrue(report["blender_version"])
        self.assertEqual(report["transport"], "blender-subprocess")

    def test_multiple_user_addons_load_with_and_without_factory_startup(self):
        fixture = ROOT / "tests" / "fixtures" / "ollama3d_fixture_addon"
        proof = ROOT / "blender" / "ollama3d_proof_addon"
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            folder = Path(folder)
            scripts = folder / "scripts"
            addons = scripts / "addons"
            addons.mkdir(parents=True)
            shutil.copytree(fixture, addons / fixture.name)
            shutil.copytree(proof, addons / proof.name)
            adapter = BlenderMcpAdapter()
            environment = {**os.environ, "BLENDER_USER_SCRIPTS": str(scripts)}
            for factory_startup in (False, True):
                label = "factory" if factory_startup else "preferences"
                report_path = folder / f"{label}-report.json"
                result_path = folder / f"{label}-result.json"
                job_path = folder / f"{label}-job.json"
                job_path.write_text(
                    json.dumps(
                        {
                            "operation": "discover",
                            "payload": {
                                "modules": [fixture.name, proof.name],
                                "report_path": str(report_path),
                                "run_id": label,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                subprocess.run(
                    adapter._subprocess_command(
                        job_path,
                        result_path,
                        modules=[fixture.name, proof.name],
                        factory_startup=factory_startup,
                    ),
                    check=True,
                    timeout=60,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertTrue(result["ok"])
                ids = set(result["result"]["operator_ids"])
                self.assertIn("ollama3d_fixture.all_types", ids)
                self.assertIn("ollama3d_proof.apply_vbom", ids)


if __name__ == "__main__":
    unittest.main()
