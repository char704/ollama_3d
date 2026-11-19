"""Small Blender add-on used only by discovery integration tests."""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

bl_info = {
    "name": "Ollama3D Discovery Fixture",
    "blender": (4, 5, 0),
    "category": "Testing",
}


class Ollama3DFixtureSettings(bpy.types.PropertyGroup):
    label: StringProperty(default="fixture")


class OLLAMA3D_FIXTURE_OT_all_types(bpy.types.Operator):
    bl_idname = "ollama3d_fixture.all_types"
    bl_label = "All fixture parameter types"
    bl_description = "Expose safe scalar, enum, path, and array RNA properties"

    flag: BoolProperty(default=True)
    count: IntProperty(default=2, min=1, max=8)
    amount: FloatProperty(default=0.5, min=0.0, max=1.0)
    title: StringProperty(default="fixture")
    mode: EnumProperty(items=(("ONE", "One", ""), ("TWO", "Two", "")), default="ONE")
    filepath: StringProperty(subtype="FILE_PATH")
    vector: FloatVectorProperty(size=3, default=(1.0, 2.0, 3.0))

    def execute(self, context):
        return {"FINISHED"}


class OLLAMA3D_FIXTURE_OT_poll_false(bpy.types.Operator):
    bl_idname = "ollama3d_fixture.poll_false"
    bl_label = "Poll false"

    @classmethod
    def poll(cls, context):
        return False

    def execute(self, context):
        return {"FINISHED"}


class OLLAMA3D_FIXTURE_OT_cancelled(bpy.types.Operator):
    bl_idname = "ollama3d_fixture.cancelled"
    bl_label = "Cancelled with report"

    def execute(self, context):
        self.report({"ERROR"}, "fixture cancellation")
        return {"CANCELLED"}


class OLLAMA3D_FIXTURE_OT_pointer(bpy.types.Operator):
    bl_idname = "ollama3d_fixture.pointer"
    bl_label = "Unsupported pointer"

    value: PointerProperty(type=Ollama3DFixtureSettings)

    def execute(self, context):
        return {"FINISHED"}


class OLLAMA3D_FIXTURE_OT_internal(bpy.types.Operator):
    bl_idname = "ollama3d_fixture.internal"
    bl_label = "Internal fixture operator"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        return {"FINISHED"}


CLASSES = (
    Ollama3DFixtureSettings,
    OLLAMA3D_FIXTURE_OT_all_types,
    OLLAMA3D_FIXTURE_OT_poll_false,
    OLLAMA3D_FIXTURE_OT_cancelled,
    OLLAMA3D_FIXTURE_OT_pointer,
    OLLAMA3D_FIXTURE_OT_internal,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
