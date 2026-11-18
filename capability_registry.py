"""Validated capability registry shared by MCP, Excel, and Blender adapters."""

import json
import re
from copy import deepcopy
from pathlib import Path

_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_VERSION = re.compile(r"\d+\.\d+\.\d+")


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
