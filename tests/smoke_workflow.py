"""Run the high-level deterministic workflow against the real local API and Blender."""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_config import data_path, load, service_url

config = load()
with httpx.Client(
    base_url=service_url(config, "api"), timeout=240, trust_env=False
) as client:
    response = client.post(
        "/workflows/bom",
        json={
            "excel_path": str(data_path(config, "inputs") / "Footwear_BOM.xlsx"),
            "model_path": str(data_path(config, "default_model")),
            "output_dir": str(data_path(config, "outputs")),
            "open_result": False,
            "force_new": True,
        },
    )
    response.raise_for_status()
    result = response.json()
    assert result["ok"] and result["status"] == "completed", result
    stored = client.get("/workflows/bom/" + result["job_id"]).json()
    assert stored["status"] == "completed"
    assert Path(stored["output"]["vbom_path"]).is_file()
    assert Path(stored["output"]["model_path"]).is_file()
print("PASS: deterministic Excel -> VBOM -> Blender -> verify workflow completed.")
print(result["job_id"])
print(result["output"]["model_path"])
