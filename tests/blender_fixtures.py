import subprocess

from adapters.common import BLENDER


def save_fixture_model(path, scene_name=None):
    setup = f"bpy.data.scenes.new({scene_name!r}); " if scene_name else ""
    subprocess.run(
        [str(BLENDER), "--background", "--factory-startup", "--python-exit-code", "1",
         "--python-expr", f"import bpy; {setup}bpy.ops.wm.save_as_mainfile(filepath={str(path)!r})"],
        check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
