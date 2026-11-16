"""Exercise queue ordering, main-thread operators, failure recovery, and scene reset."""

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_config import ROOT, load, service_url

sys.stdout.reconfigure(encoding="utf-8")
config = load()
evidence = {}

with httpx.Client(
    base_url=service_url(config, "api"), timeout=180, trust_env=False
) as client:
    agent = client.post("/blender/agent/start").json()
    assert agent["ready"]
    exposed = client.get("/blender/operators").json()["operators"]
    assert {"add_cube", "add_uv_sphere", "start_rhino_server"} <= {
        item["id"] for item in exposed
    }
    assert "agent_reset_failure_test" not in {item["id"] for item in exposed}

    def submit(operator_id, parameters=None, wait=True):
        response = client.post(
            "/blender/operators/run",
            json={
                "operator_id": operator_id,
                "parameters": parameters or {},
                "wait_for_completion": wait,
            },
        )
        response.raise_for_status()
        return response.json()

    def wait_job(job_id):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            job = client.get("/blender/jobs/" + job_id).json()
            if job["status"] in ("completed", "failed", "interrupted"):
                return job
            time.sleep(0.2)
        raise TimeoutError(job_id)

    first = submit("add_cube", {"size": 1.25}, wait=False)
    second = submit("add_uv_sphere", {"segments": 16, "ring_count": 8}, wait=False)
    first = wait_job(first["job_id"])
    second = wait_job(second["job_id"])
    assert first["status"] == second["status"] == "completed"
    assert first["agent_pid"] == second["agent_pid"] == agent["pid"]
    assert (
        first["agent_instance_id"]
        == second["agent_instance_id"]
        == agent["instance_id"]
    )
    assert first["started_at"] <= second["started_at"]
    for job in (first, second):
        assert job["reset_before"]["object_count"] == 0
        assert job["reset_after"]["object_count"] == 0
        assert Path(job["output_path"]).is_file()

    failed = submit("agent_reset_failure_test")
    assert failed["status"] == "failed" and failed["reset_after"]["object_count"] == 0
    recovered = submit("add_cube", {"size": 0.75})
    assert recovered["status"] == "completed"
    assert recovered["agent_pid"] == agent["pid"]
    assert recovered["reset_before"]["object_count"] == 0
    assert recovered["objects_after_operator"] == ["Cube"]
    assert recovered["reset_after"]["object_count"] == 0

    evidence = {
        "agent": agent,
        "queued_jobs": [first, second],
        "failed_job": failed,
        "recovered_job": recovered,
    }

(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence" / "agent-smoke.json").write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    "PASS: queue order, same Blender PID, main-thread built-in operators, failure recovery, and clean scene reset."
)
print("Agent PID:", agent["pid"])
