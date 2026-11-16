"""Validate static schemas and representative project contracts."""

import json
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts import validate_contract, validator
from project_config import load


class ContractTests(unittest.TestCase):
    def test_all_schemas_are_valid(self):
        for name in (
            "job",
            "workflow",
            "tool-manifest",
            "tool-result",
            "material-recipe",
        ):
            self.assertIsNotNone(validator(name))

    def test_project_tool_manifests_match_schema(self):
        config = load()
        for path in config["_tool_catalog"]["manifest_paths"]:
            value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            validate_contract("tool-manifest", value)

    def test_workflow_definitions_match_schema(self):
        root = Path(__file__).resolve().parents[1] / "workflows" / "definitions"
        for path in root.glob("*.json"):
            validate_contract(
                "workflow", json.loads(path.read_text(encoding="utf-8-sig"))
            )

    def test_job_and_material_examples(self):
        validate_contract(
            "job",
            {
                "job_id": uuid.uuid4().hex,
                "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        validate_contract(
            "material-recipe",
            {
                "schema_version": 1,
                "regions": {
                    "Upper": {
                        "material_type": "knitted_mesh",
                        "base_color": "#26384A",
                        "roughness": 0.78,
                        "metallic": 0.0,
                    }
                },
            },
        )

    def test_invalid_recipe_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "base_color"):
            validate_contract(
                "material-recipe",
                {
                    "schema_version": 1,
                    "regions": {
                        "Upper": {
                            "material_type": "mesh",
                            "base_color": "blue",
                            "roughness": 2,
                            "metallic": 0,
                        }
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
