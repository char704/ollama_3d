"""Validated capability registry shared by the agent, Excel, and Blender adapters."""

import json
import re
import threading
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
    if "params" in item and not isinstance(params, dict):
        raise ValueError(f"capabilities.json: {capability_id}.params must be an object")
    docs = item.get("docs")
    if docs is not None:
        if not isinstance(docs, str) or not docs.strip():
            raise ValueError(f"capabilities.json: {capability_id}.docs must be a non-empty string")
        path = Path(docs)
        valid_knowledge = path.parts and path.parts[0] == "knowledge"
        valid_addon = (
            len(path.parts) >= 3
            and path.parts[0] == "addons"
            and path.parts[1] == item.get("addon_module")
        )
        if path.is_absolute() or ".." in path.parts or not (valid_knowledge or valid_addon):
            raise ValueError(
                f"capabilities.json: {capability_id}.docs must be inside knowledge/ or its add-on folder"
            )
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
                if not _ADDON_MODULE.fullmatch(item["addon_module"]):
                    raise ValueError(f"capabilities.json: {capability_id}.addon_module is invalid")
                if not isinstance(item["params"], dict):
                    raise ValueError(f"capabilities.json: {capability_id}.params must be an object")
                if item["risk"] not in _RISKS:
                    raise ValueError(f"capabilities.json: {capability_id}.risk is invalid")
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
        }


def load_registry(path, addon_root=None, workflow_root=None):
    path = Path(path).resolve()
    return ReloadingCapabilityRegistry(path, addon_root, workflow_root)


def _safe_name(value):
    value = re.sub(r"[^a-z0-9_]+", "_", value.casefold()).strip("_")
    return value if value and value[0].isalpha() else "operator_" + value


class ReloadingCapabilityRegistry:
    """Merge the base registry with add-on packs and reload when files change."""

    def __init__(self, path, addon_root=None, workflow_root=None):
        self.path = Path(path).resolve()
        self.addon_root = Path(addon_root or self.path.parent / "addons").resolve()
        self.workflow_root = Path(
            workflow_root or self.path.parent / "workflows" / "definitions"
        ).resolve()
        self._lock = threading.RLock()
        self._snapshot = None
        self._registry = None
        self._workflows = {}
        self._refresh()

    def _files(self):
        files = [self.path]
        if self.addon_root.is_dir():
            files.extend(sorted(self.addon_root.glob("*/addon.json")))
            files.extend(sorted(self.addon_root.glob("*/docs.md")))
            files.extend(sorted(self.addon_root.glob("*/workflows/*.json")))
        if self.workflow_root.is_dir():
            files.extend(sorted(self.workflow_root.glob("*.json")))
        return files

    def _state(self):
        return tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in self._files()
        )

    def _pack_entries(self, path):
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        module = document.get("module", "")
        if not _ADDON_MODULE.fullmatch(module) or path.parent.name != module:
            raise ValueError(f"{path}: module must match its add-on folder name")
        description = document.get("description", "")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{path}: description must be a non-empty string")
        operators = document.get("operators")
        if not isinstance(operators, dict) or not operators:
            raise ValueError(f"{path}: operators must be a non-empty object")
        default_docs = path.parent / "docs.md"
        entries = []
        for target, settings in operators.items():
            if not _OPERATOR.fullmatch(target) or not isinstance(settings, dict):
                raise ValueError(f"{path}: invalid operator entry: {target}")
            action = target.split(".", 1)[1]
            module_id = ".".join(_safe_name(part) for part in module.split("."))
            docs = settings.get("docs")
            if docs is None and default_docs.is_file():
                docs_path = default_docs
            elif docs is not None:
                docs_path = (path.parent / docs).resolve()
                if not docs_path.is_relative_to(path.parent.resolve()):
                    raise ValueError(f"{path}: operator docs must stay inside the add-on folder")
                if not docs_path.is_file():
                    raise ValueError(f"{path}: operator docs do not exist: {docs}")
            else:
                docs_path = None
            entry = {
                "id": settings.get("id", f"blender.{module_id}.{_safe_name(action)}"),
                "provider": "blender_operator",
                "handler": "generic_operator",
                "target": target,
                "addon_module": module,
                "description": settings.get("description") or description,
                "risk": settings.get("risk", "mutating"),
                "params": settings.get("params"),
                "expose": "generic",
                "background_safe": settings.get("background_safe", False),
                "enabled": settings.get("enabled", False),
            }
            if docs_path is not None:
                entry["docs"] = (
                    Path("addons") / module / docs_path.relative_to(path.parent.resolve())
                ).as_posix()
            entries.append(entry)
        return entries

    def _refresh(self):
        with self._lock:
            state = self._state()
            if state == self._snapshot:
                return
            base = json.loads(self.path.read_text(encoding="utf-8-sig"))
            capabilities = list(base.get("capabilities", []))
            for pack in sorted(self.addon_root.glob("*/addon.json")) if self.addon_root.is_dir() else []:
                capabilities.extend(self._pack_entries(pack))
            merged = {"schema_version": base.get("schema_version"), "capabilities": capabilities}
            registry = CapabilityRegistry(self.path, merged)

            from workflow_definitions import validate_definition

            workflows = {}
            workflow_files = []
            if self.workflow_root.is_dir():
                workflow_files.extend(sorted(self.workflow_root.glob("*.json")))
            if self.addon_root.is_dir():
                workflow_files.extend(sorted(self.addon_root.glob("*/workflows/*.json")))
            for workflow_path in workflow_files:
                definition = validate_definition(
                    json.loads(workflow_path.read_text(encoding="utf-8-sig"))
                )
                workflow_id = definition["id"]
                if workflow_id in workflows:
                    raise ValueError(f"Duplicate workflow id: {workflow_id}")
                workflows[workflow_id] = definition
            self._registry = registry
            self._workflows = workflows
            self._snapshot = state

    def require(self, *args, **kwargs):
        self._refresh()
        return self._registry.require(*args, **kwargs)

    def items(self, *args, **kwargs):
        self._refresh()
        return self._registry.items(*args, **kwargs)

    def generic_capabilities(self):
        self._refresh()
        return self._registry.generic_capabilities()

    def addon_modules(self, *args, **kwargs):
        self._refresh()
        return self._registry.addon_modules(*args, **kwargs)

    def summary(self):
        self._refresh()
        result = self._registry.summary()
        result["addon_root"] = str(self.addon_root)
        result["workflows"] = len(self._workflows)
        return result

    def workflows(self):
        self._refresh()
        return [deepcopy(value) for value in self._workflows.values()]

    def require_workflow(self, workflow_id):
        self._refresh()
        try:
            return deepcopy(self._workflows[workflow_id])
        except KeyError as exc:
            raise ValueError(f"Workflow definition is not registered: {workflow_id}") from exc
