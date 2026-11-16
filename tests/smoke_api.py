"""Real HTTP/Blender smoke test: existing BOM plus a generated color variant."""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
import tempfile
from pathlib import Path
import httpx
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_config import ROOT, load, data_path, service_url
from adapters.excel import read_bom

config = load()
assert all(
    item["provider"] == "local" for item in config["workflow"].values()
), "This smoke test requires local workflow providers"
source = data_path(config, "inputs") / "Footwear_BOM.xlsx"
outputs = data_path(config, "outputs")
evidence = []
with tempfile.TemporaryDirectory(prefix="smoke-", dir=ROOT / "tests") as folder:
    variant = Path(folder) / "BOM_Test_Purple.xlsx"
    assert variant.resolve().is_relative_to(ROOT / "tests")
    workbook = load_workbook(source)
    sheet = workbook["BOM"]
    for row, color in zip(range(2, 5), ["#9B30FF", "#B6FF00", "#FF1493"]):
        sheet.cell(row, 3, color)
    workbook.save(variant)
    workbook.close()
    with httpx.Client(
        base_url=service_url(config, "api"), timeout=210, trust_env=False
    ) as client:
        for excel in (source, variant):
            expected = read_bom(excel)
            # Empty output_dir exercises the shared config default.
            response = client.post(
                "/excel/export-vbom", json={"excel_path": str(excel)}
            )
            response.raise_for_status()
            exported = response.json()
            assert Path(exported["vbom_path"]).is_relative_to(outputs)
            assert (
                client.get("/results/" + exported["run_id"]).json()["status"]
                == "exported"
            )
            body = {"vbom_path": exported["vbom_path"], "open_window": False}
            response = client.post("/blender/apply-vbom", json=body)
            response.raise_for_status()
            applied = response.json()
            assert (
                applied["status"] == "completed"
                and applied["verified_after_reopen"]
                and not applied["window_opened"]
            )
            for wanted in expected:
                actual = next(
                    r for r in applied["applied"] if r["object"] == wanted["object"]
                )
                assert all(actual[key] == wanted[key] for key in wanted)
            assert (
                Path(applied["output"]).is_file() and Path(applied["preview"]).is_file()
            )
            assert (
                client.get("/results/" + exported["run_id"]).json()["status"]
                == "completed"
            )
            assert client.post("/blender/apply-vbom", json=body).json()["reused_result"]
            evidence.append(
                {"expected": expected, "export": exported, "apply": applied}
            )
            print(excel.name, "PASS", applied["output"], flush=True)
(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence/api-smoke.json").write_text(
    json.dumps(evidence, indent=2), encoding="utf-8"
)
