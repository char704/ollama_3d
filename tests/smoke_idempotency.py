"""Verify equivalent full and short paths do not execute the BOM workflow twice."""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_config import data_path, load, service_url

config = load()
source = data_path(config, "inputs") / "Footwear_BOM.xlsx"
base = service_url(config, "api")
common = {
    "model_path": str(data_path(config, "default_model")),
    "output_dir": str(data_path(config, "outputs")),
    "open_result": False,
}
with httpx.Client(base_url=base, timeout=240, trust_env=False) as client:
    first = client.post(
        "/workflows/bom",
        json={**common, "excel_path": str(source), "force_new": True},
    ).json()
    second = client.post(
        "/workflows/bom",
        json={**common, "excel_path": source.name, "force_new": False},
    ).json()
assert first["status"] == "completed", first
assert second["job_id"] == first["job_id"], (first, second)
assert second["reused_job"] is True
print("PASS: equivalent workflow request reused the completed job.")
print(first["job_id"])
