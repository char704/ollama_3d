import unittest
from copy import deepcopy

from capability_registry import CapabilityRegistry
from project_config import ROOT


BASE = {
    "schema_version": 1,
    "capabilities": [
        {
            "id": "system.status",
            "provider": "system",
            "handler": "status",
            "target": "local.readiness",
            "enabled": True,
        }
    ],
}


class RegistryExtensionTests(unittest.TestCase):
    def test_legacy_entry_remains_valid(self):
        registry = CapabilityRegistry(ROOT / "legacy-capabilities.json", deepcopy(BASE))
        self.assertEqual(registry.items(), BASE["capabilities"])

    def test_blender_operator_requires_params(self):
        document = deepcopy(BASE)
        document["capabilities"].append(
            {
                "id": "blender.fixture.run",
                "provider": "blender_operator",
                "handler": "generic_operator",
                "target": "fixture.run",
                "addon_module": "fixture_addon",
                "risk": "mutating",
                "enabled": False,
            }
        )
        with self.assertRaisesRegex(ValueError, "params.*required"):
            CapabilityRegistry(ROOT / "test-capabilities.json", document)

    def test_expose_only_accepts_generic(self):
        document = deepcopy(BASE)
        document["capabilities"][0]["expose"] = "direct"
        with self.assertRaisesRegex(ValueError, "expose"):
            CapabilityRegistry(ROOT / "test-capabilities.json", document)

    def test_docs_must_stay_inside_knowledge(self):
        document = deepcopy(BASE)
        document["capabilities"][0]["docs"] = "../private.md"
        with self.assertRaisesRegex(ValueError, "knowledge"):
            CapabilityRegistry(ROOT / "test-capabilities.json", document)

    def test_generic_capabilities_and_addon_modules_are_stable_copies(self):
        document = deepcopy(BASE)
        document["capabilities"].extend(
            [
                {
                    "id": "blender.fixture.first",
                    "provider": "blender_operator",
                    "handler": "generic_operator",
                    "target": "fixture.first",
                    "addon_module": "fixture_addon",
                    "risk": "read",
                    "params": {"type": "object", "properties": {}},
                    "expose": "generic",
                    "enabled": True,
                },
                {
                    "id": "blender.fixture.second",
                    "provider": "blender_operator",
                    "handler": "generic_operator",
                    "target": "fixture.second",
                    "addon_module": "fixture_addon",
                    "risk": "mutating",
                    "params": {"type": "object", "properties": {}},
                    "enabled": False,
                },
            ]
        )
        registry = CapabilityRegistry(ROOT / "test-capabilities.json", document)
        generic = registry.generic_capabilities()
        generic[0]["enabled"] = False
        self.assertTrue(registry.require("blender.fixture.first")["enabled"])
        self.assertEqual(registry.addon_modules(), ["fixture_addon"])
        self.assertEqual(registry.addon_modules(enabled_only=False), ["fixture_addon"])


if __name__ == "__main__":
    unittest.main()
