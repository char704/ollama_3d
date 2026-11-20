import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from adapters.common import BLENDER, ROOT


def index_entry(name, sockets_in, sockets_out):
    def sockets(values):
        return [{"name": name, "value": socket_type} for name, socket_type in values]

    return {
        "name": "NT" + name,
        "properties": [{
            "name": "AssetMetaData.properties",
            "value": [
                {"name": "inputs", "value": sockets(sockets_in)},
                {"name": "outputs", "value": sockets(sockets_out)},
            ],
        }],
    }


COLOR = [("Color", "Color")]
MATERIAL_IN = [("Color", "Color"), ("Normal Blend", "Color")]
MATERIAL_OUT = [("Surface", "Shader"), ("Normal Normal Map", "Color")]


@unittest.skipUnless(BLENDER.is_file(), "Configured Blender executable is unavailable")
@unittest.skipUnless((ROOT / "addons/jhv_dpc/jhv_dpc.py").is_file(), "Internal JHV add-on is not available")
class JHVAssetIndexTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.library = self.root / "libraries"
        self.generic = self.library / "Generic Library"
        self.adidas = self.library / "Adidas Library"
        self.generic.mkdir(parents=True)
        self.adidas.mkdir()
        self.env = dict(os.environ, LOCALAPPDATA=str(self.root / "local"),
                        BLENDER_USER_SCRIPTS=str(self.root / "scripts"),
                        BLENDER_USER_CONFIG=str(self.root / "config"), PYTHONHASHSEED="0",
                        PYTHONIOENCODING="utf-8")
        addons = self.root / "scripts" / "addons"
        addons.mkdir(parents=True)
        shutil.copy2(ROOT / "addons" / "jhv_dpc" / "jhv_dpc.py", addons)
        self.cache = self.root / "local" / "Blender Foundation" / "Blender" / "cache"
        self.indexes = self.cache / "asset-library-indices"
        self.indexes.mkdir(parents=True)

    def run_command(self, command, success=True):
        result = subprocess.run(command, cwd=ROOT, env=self.env, text=True,
                                capture_output=True, timeout=90, encoding="utf-8")
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout

    def blender(self, expression, model=None):
        command = [str(BLENDER), "--background"]
        if model:
            command.append(str(model))
        return self.run_command(command + ["--addons", "jhv_dpc", "--python-exit-code", "1",
                                           "--python-expr", expression])

    def cli(self, *args, success=True):
        return json.loads(self.run_command(
            [sys.executable, str(ROOT / "scripts" / "jhv_cli.py"), *map(str, args)], success
        ))

    def write_index(self, filename, entries):
        path = self.indexes / f"123abc_{filename}.index.json"
        path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        return path

    def configure(self):
        self.blender(
            "import bpy; "
            f"bpy.context.preferences.addons['jhv_dpc'].preferences.library_base_path={str(self.library)!r}; "
            "bpy.ops.wm.save_userpref()"
        )

    def test_refresh_reuses_json_and_failure_preserves_previous_snapshot(self):
        self.configure()
        (self.generic / "a.blend").touch()
        a = self.write_index("a.blend", [index_entry("A", COLOR, COLOR)])
        first = self.cli("refresh-index")
        self.assertEqual((first["generation"], first["parsed_index_files"]), (1, 1))
        b_blend = self.generic / "b.blend"
        b_blend.touch()
        b = self.write_index("b.blend", [index_entry("B", COLOR, COLOR)])
        second = self.cli("refresh-index")
        self.assertEqual((second["nodes"], second["parsed_index_files"], second["reused_index_files"]), (2, 1, 1))
        b.write_text("{broken index", encoding="utf-8")
        self.assertFalse(self.cli("refresh-index", success=False)["ok"])
        with closing(sqlite3.connect(second["path"])) as connection:
            self.assertEqual(connection.execute("SELECT value FROM metadata WHERE key='generation'").fetchone(), ("2",))
            self.assertEqual(connection.execute("SELECT name FROM assets ORDER BY name").fetchall(), [("A",), ("B",)])
        b.unlink()
        b_blend.rename(self.generic / "c.blend")
        self.write_index("c.blend", [index_entry("C", COLOR, COLOR)])
        a.write_text(json.dumps({"entries": [index_entry("AA", COLOR, COLOR)]}), encoding="utf-8")
        third = self.cli("refresh-index")
        self.assertEqual((third["nodes"], third["parsed_index_files"]), (2, 2))
        with closing(sqlite3.connect(third["path"])) as connection:
            self.assertEqual(connection.execute("SELECT name FROM assets ORDER BY name").fetchall(), [("AA",), ("C",)])

    def test_real_workflow_compare_sqlite_and_stale_source_fallback(self):
        model = self.root / "source.blend"
        color_file = self.adidas / "color.blend"
        mat_file = self.generic / "material.blend"
        fallback_mat = self.generic / "base_library.blend"
        fallback_color = self.adidas / "Colors" / "all_colors.blend"
        fallback_color.parent.mkdir()
        self.blender(f"""
import bpy
bpy.context.preferences.addons['jhv_dpc'].preferences.library_base_path = {str(self.library)!r}
bpy.ops.wm.save_userpref()
def write(name, path, inputs, outputs):
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    for direction, sockets in [('INPUT', inputs), ('OUTPUT', outputs)]:
        for socket, kind in sockets:
            group.interface.new_socket(name=socket, in_out=direction, socket_type='NodeSocket' + kind)
    bpy.data.libraries.write(path, {{group}})
    bpy.data.node_groups.remove(group)
write('CL_early', {str(color_file)!r}, {COLOR!r}, {COLOR!r})
write('MT', {str(mat_file)!r}, {MATERIAL_IN!r}, {MATERIAL_OUT!r})
write('FX_material', {str(fallback_mat)!r}, {COLOR!r}, {COLOR!r})
write('FX_color', {str(fallback_color)!r}, {COLOR!r}, {COLOR!r})
bpy.context.scene.name = 'Model'
bpy.data.collections['Collection'].name = 'Model'
bpy.data.objects['Cube'].name = 'Upper'
material = bpy.data.materials.new('Fixture')
material.use_nodes = True
bpy.data.objects['Upper'].data.materials.clear()
bpy.data.objects['Upper'].data.materials.append(material)
bpy.ops.wm.save_as_mainfile(filepath={str(model)!r})
""")
        self.write_index(color_file.name, [
            index_entry("CL_early", COLOR, COLOR),
            index_entry("cl_token", COLOR, COLOR),
        ])
        self.write_index(mat_file.name, [index_entry("MT", MATERIAL_IN, MATERIAL_OUT)])
        vbom = self.root / "source.vbom"
        vbom.write_text(
            '<VBOM><Part name="Upper|AB1234"><VPart mat_id="MT" color_code="CL_early"/></Part>'
            '<Part name="Missing|AB1234"><VPart color_code="UNKNOWN"/></Part>'
            '<Part name="Other|AB1234"><VPart color_code="FX_test"/></Part>'
            '<Part name="Prefix|AB1234"><VPart color_code="CL_TOKEN"/></Part></VBOM>', encoding="utf-8"
        )
        refreshed = self.cli("refresh-index")
        database = Path(refreshed["path"])
        # Large catalog fixture. These unrelated entries never require a source file check.
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executemany(
                "INSERT INTO assets VALUES ('COLOR', ?, ?, ?, '', 0, 0, '', 0, 0)",
                ((f"Other-{i}", f"other-{i}", i + 100) for i in range(100_000)),
            )
            connection.execute("UPDATE metadata SET value='100003' WHERE key='nodes'")

        def apply(mode):
            run = self.cli("apply", vbom, self.root / "out", "--model", model, "--resolver", mode)
            return json.loads(Path(run["evidence"]["blender"]).read_text(encoding="utf-8")), run

        compared, compare_run = apply("compare")
        diag = compared["asset_resolver"]
        self.assertEqual((diag["effective_mode"], diag["compared_ids"]), ("legacy", 5))
        self.assertTrue(diag["comparison_complete"])
        self.assertEqual(diag["differences"], [])
        indexed, index_run = apply("sqlite")
        diag = indexed["asset_resolver"]
        self.assertEqual(diag["effective_mode"], "sqlite")
        self.assertEqual(diag["nodes"], 100003)
        self.assertEqual(diag["validated_paths"], 4)
        self.assertNotIn("legacy_cache", diag)
        self.assertEqual(diag["unmatched_ids"]["COLOR"], ["UNKNOWN"])
        self.assertEqual(diag["distinct_import_files"], 3)
        self.assertIn("blender_subprocess_wall_seconds", indexed["timings"])
        self.assertEqual(compared["warnings"], indexed["warnings"])

        def material_groups(run):
            return self.blender(
                "import bpy; obj=bpy.data.scenes['AB1234'].objects['Upper|AB1234']; "
                "print('GROUPS=' + repr(sorted(n.node_tree.name for n in obj.material_slots[0].material.node_tree.nodes if n.type=='GROUP')))",
                model=run["output_path"],
            ).split("GROUPS=", 1)[1].splitlines()[0]

        assigned_groups = material_groups(index_run)
        self.assertEqual(material_groups(compare_run), assigned_groups)
        self.assertIn("CL_early", assigned_groups)
        with color_file.open("ab") as stream:
            stream.write(b"changed")
        stale, _ = apply("sqlite")
        self.assertEqual(stale["asset_resolver"]["effective_mode"], "legacy")
        self.assertIn("Asset source changed", stale["asset_resolver"]["fallback_reason"])
        self.assertTrue(stale["verified_after_reopen"])
