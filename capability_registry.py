"""Validated capability registry shared by MCP, Excel, and Blender adapters."""

import json
import re
from copy import deepcopy
from pathlib import Path

_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_ADDON_MODULE = re.compile(r"[a-z][a-z0-9_.]*")
_OPERATOR = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
_RISKS = {"read", "mutating", "filesystem"}


def _validate_optional_fields(capability_id, item):
    for field in ("description", "instructions"):
        value = item.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"capabilities.json: {capability_id}.{field} must be a non-empty string")
    addon_module = item.get("addon_module")
    if addon_module is not None and (
        not isinstance(addon_module, str) or not _ADDON_MODULE.fullmatch(addon_module)
    ):
        raise ValueError(f"capabilities.json: {capability_id}.addon_module is invalid")
    risk = item.get("risk")
    if risk is not None and risk not in _RISKS:
        raise ValueError(f"capabilities.json: {capability_id}.risk is invalid")
    params = item.get("params")
    if params is not None and not isinstance(params, dict):
        raise ValueError(f"capabilities.json: {capability_id}.params must be an object")
    docs = item.get("docs")
    if docs is not None:
        if not isinstance(docs, str) or not docs.strip():
            raise ValueError(f"capabilities.json: {capability_id}.docs must be a non-empty string")
        path = Path(docs)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "knowledge":
            raise ValueError(f"capabilities.json: {capability_id}.docs must be inside knowledge/")
    expose = item.get("expose")
    if expose is not None and expose != "generic":
        raise ValueError(f"capabilities.json: {capability_id}.expose must be 'generic'")
    background_safe = item.get("background_safe")
    if background_safe is not None and type(background_safe) is not bool:
        raise ValueError(f"capabilities.json: {capability_id}.background_safe must be boolean")


class CapabilityRegistry:
    def __init__(self, path, document):
        self.path = Path(path).resolve()
        if document.get("schema_version") != 1:
            raise ValueError("capabilities.json: schema_version must be 1")
        items = document.get("capabilities")
        if not isinstance(items, list) or not items:
            raise ValueError("capabilities.json: capabilities must be a non-empty list")
        self._items = {}
        public_tools = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"capabilities.json: capability {index} must be an object")
            capability_id = item.get("id", "")
            if not _ID.fullmatch(capability_id) or capability_id in self._items:
                raise ValueError(f"capabilities.json: invalid or duplicate id: {capability_id!r}")
            for field in ("provider", "handler"):
                if not _NAME.fullmatch(item.get(field, "")):
                    raise ValueError(f"capabilities.json: {capability_id}.{field} is invalid")
            if not isinstance(item.get("target"), str) or not item["target"].strip():
                raise ValueError(f"capabilities.json: {capability_id}.target is required")
            if type(item.get("enabled")) is not bool:
                raise ValueError(f"capabilities.json: {capability_id}.enabled must be boolean")
            version = item.get("version")
            if version is not None and not _VERSION.fullmatch(version):
                raise ValueError(f"capabilities.json: {capability_id}.version is invalid")
            tool = item.get("public_tool")
            if tool is not None:
                if not _NAME.fullmatch(tool) or tool in public_tools:
                    raise ValueError(f"capabilities.json: invalid or duplicate public_tool: {tool!r}")
                public_tools.add(tool)
            dependencies = item.get("dependencies", [])
            if not isinstance(dependencies, list) or not all(isinstance(value, str) for value in dependencies):
                raise ValueError(f"capabilities.json: {capability_id}.dependencies must be a string list")
            if not isinstance(item.get("settings", {}), dict):
                raise ValueError(f"capabilities.json: {capability_id}.settings must be an object")
            _validate_optional_fields(capability_id, item)
            if item["provider"] == "blender_operator":
                for field in ("addon_module", "params", "risk"):
                    if field not in item:
                        raise ValueError(
                            f"capabilities.json: {capability_id}.{field} is required for blender_operator"
                        )
                if not _OPERATOR.fullmatch(item["target"]):
                    raise ValueError(
                        f"capabilities.json: {capability_id}.target must be category.name"
                    )
            self._items[capability_id] = dict(item)
        for capability in self._items.values():
            for dependency in capability.get("dependencies", []):
                if dependency not in self._items:
                    raise ValueError(
                        f"capabilities.json: {capability['id']} has unknown dependency {dependency}"
                    )
        visiting = set()
        visited = set()

        def visit(capability_id):
            if capability_id in visiting:
                raise ValueError(f"capabilities.json: dependency cycle at {capability_id}")
            if capability_id in visited:
                return
            visiting.add(capability_id)
            for dependency in self._items[capability_id].get("dependencies", []):
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)

        for capability_id in self._items:
            visit(capability_id)

    def require(self, capability_id, provider=None, handler=None):
        try:
            item = self._items[capability_id]
        except KeyError as exc:
            raise RuntimeError(f"Capability is not registered: {capability_id}") from exc
        if not item["enabled"]:
            raise RuntimeError(f"Capability is disabled: {capability_id}")
        if provider is not None and item["provider"] != provider:
            raise RuntimeError(f"Capability provider mismatch: {capability_id}")
        if handler is not None and item["handler"] != handler:
            raise RuntimeError(f"Capability handler mismatch: {capability_id}")
        for dependency in item.get("dependencies", []):
            self.require(dependency)
        return deepcopy(item)

    def public_tools(self):
        return [
            item["public_tool"]
            for item in self._items.values()
            if item["enabled"] and item.get("public_tool")
        ]

    def items(self, provider=None, enabled_only=True):
        return [
            deepcopy(item)
            for item in self._items.values()
            if (not enabled_only or item["enabled"])
            and (provider is None or item["provider"] == provider)
        ]

    def generic_capabilities(self):
        return [
            deepcopy(item)
            for item in self._items.values()
            if item["enabled"]
            and item["provider"] == "blender_operator"
            and item.get("expose") == "generic"
            and all(self._items[dependency]["enabled"] for dependency in item.get("dependencies", []))
        ]

    def addon_modules(self, enabled_only=True):
        modules = []
        for item in self._items.values():
            module = item.get("addon_module")
            if module and (not enabled_only or item["enabled"]) and module not in modules:
                modules.append(module)
        return modules

    def summary(self):
        enabled = [item for item in self._items.values() if item["enabled"]]
        return {
            "schema_version": 1,
            "path": str(self.path),
            "registered": len(self._items),
            "enabled": len(enabled),
            "public_tools": self.public_tools(),
        }


def load_registry(path):
    path = Path(path).resolve()
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    return CapabilityRegistry(path, document)
