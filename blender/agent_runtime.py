"""Long-running Blender process that executes queued operators on Blender's main thread."""

import atexit
import datetime
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

import bpy


def now():
    return datetime.datetime.now().astimezone().isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


root_text, config_text, bootstrap_text = sys.argv[sys.argv.index("--") + 1 :]
ROOT = Path(root_text).resolve()
CONFIG = read_json(config_text)
BOOTSTRAP = Path(bootstrap_text)
AGENT_ROOT = ROOT / "runtime" / "blender-agent"
JOBS = AGENT_ROOT / "jobs"
QUEUE = AGENT_ROOT / "queue"
STATE = AGENT_ROOT / "state.json"
STOP = AGENT_ROOT / "stop.request.json"
TEMPLATE = AGENT_ROOT / "empty-template.blend"
INSTANCE_ID = uuid.uuid4().hex

bootstrap_deadline = time.monotonic() + 10
while not BOOTSTRAP.is_file() and time.monotonic() < bootstrap_deadline:
    time.sleep(0.05)
if not BOOTSTRAP.is_file():
    raise RuntimeError("Blender Agent bootstrap file was not created")
BOOTSTRAP_DATA = read_json(BOOTSTRAP)
BOOTSTRAP.unlink(missing_ok=True)

OPERATORS = {
    item["id"]: item
    for item in CONFIG.get("blender_operators", [])
    if item.get("enabled", True) and item.get("execution_mode") == "one_shot"
}
AGENT_CONFIG = CONFIG["blender_agent"]
CURRENT_JOB = None
LAST_HEARTBEAT = 0.0


def write_state(status="idle", current_job=None, **updates):
    value = {
        "pid": os.getpid(),
        "create_time": BOOTSTRAP_DATA["create_time"],
        "fingerprint": BOOTSTRAP_DATA["fingerprint"],
        "instance_id": INSTANCE_ID,
        "status": status,
        "current_job": current_job,
        "heartbeat_at": now(),
        "template_path": str(TEMPLATE),
    }
    value.update(updates)
    write_json(STATE, value)
    return value


def clear_scene_for_template():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    try:
        bpy.data.orphans_purge(do_recursive=True)
    except Exception:
        pass
    bpy.ops.wm.save_as_mainfile(filepath=str(TEMPLATE), check_existing=False)


def recover_interrupted_jobs():
    for path in JOBS.glob("*.json"):
        try:
            job = read_json(path)
        except Exception:
            continue
        if job.get("status") == "running":
            job.update(
                ok=False,
                status="interrupted",
                finished_at=now(),
                error="The previous Blender Agent stopped while this job was running.",
            )
            write_json(path, job)
        elif job.get("status") == "queued":
            write_json(
                QUEUE / path.name,
                {"job_id": job["job_id"], "created_at": job.get("created_at", "")},
            )


def reset_scene(model_path=""):
    source = Path(model_path) if model_path else TEMPLATE
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    return {
        "source": str(source),
        "object_count": len(bpy.data.objects),
        "objects": sorted(obj.name for obj in bpy.data.objects),
    }


def find_operator(identifier):
    group_name, operator_name = identifier.split(".")
    group = getattr(bpy.ops, group_name, None)
    operator = getattr(group, operator_name, None) if group else None
    if operator is None:
        raise RuntimeError(
            "Operator is not registered in this Blender profile: bpy.ops." + identifier
        )
    return operator


def run_job(path, queue_marker):
    global CURRENT_JOB
    job = read_json(path)
    if job.get("status") != "queued":
        return
    CURRENT_JOB = job["job_id"]
    job.update(
        status="running",
        started_at=now(),
        agent_pid=os.getpid(),
        agent_instance_id=INSTANCE_ID,
    )
    write_json(path, job)
    queue_marker.unlink(missing_ok=True)
    write_state("busy", CURRENT_JOB)
    reset_after = None
    try:
        item = OPERATORS.get(job["operator_id"])
        if item is None or item["operator"] != job["operator"]:
            raise RuntimeError(
                "The queued operator is not in the active one-shot allowlist"
            )
        reset_before = reset_scene(job.get("model_path", ""))
        operator = find_operator(item["operator"])
        blender_result = set(operator(**job["parameters"]))
        if "FINISHED" not in blender_result:
            raise RuntimeError("Operator returned " + repr(blender_result))
        objects_after_operator = sorted(obj.name for obj in bpy.data.objects)
        output_path = job.get("output_path", "")
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=output_path, check_existing=False)
        reset_after = reset_scene()
        job.update(
            ok=True,
            status="completed",
            finished_at=now(),
            blender_result=sorted(blender_result),
            reset_before=reset_before,
            objects_after_operator=objects_after_operator,
            reset_after=reset_after,
        )
    except Exception as exc:
        try:
            reset_after = reset_scene()
        except Exception as reset_exc:
            reset_after = {"ok": False, "error": str(reset_exc)}
        job.update(
            ok=False,
            status="failed",
            finished_at=now(),
            error=str(exc),
            traceback=traceback.format_exc(),
            reset_after=reset_after,
        )
    write_json(path, job)
    CURRENT_JOB = None
    write_state("idle")


def next_job():
    queued = []
    for marker in QUEUE.glob("*.json"):
        try:
            queued_item = read_json(marker)
            job_path = JOBS / (queued_item["job_id"] + ".json")
            job = read_json(job_path)
        except Exception:
            marker.unlink(missing_ok=True)
            continue
        if job.get("status") == "queued":
            queued.append((job.get("created_at", ""), job_path, marker))
        else:
            marker.unlink(missing_ok=True)
    selected = min(queued, default=(None, None, None))
    return selected[1], selected[2]


def poll_queue():
    global LAST_HEARTBEAT
    if STOP.is_file() and CURRENT_JOB is None:
        write_state("stopping")
        STOP.unlink(missing_ok=True)
        bpy.ops.wm.quit_blender()
        return None
    path, marker = next_job()
    if path:
        run_job(path, marker)
        LAST_HEARTBEAT = time.monotonic()
    elif time.monotonic() - LAST_HEARTBEAT >= float(
        AGENT_CONFIG["heartbeat_interval_seconds"]
    ):
        write_state("idle")
        LAST_HEARTBEAT = time.monotonic()
    return float(AGENT_CONFIG["poll_interval_seconds"])


def mark_stopped():
    try:
        write_state("stopped")
    except Exception:
        pass


AGENT_ROOT.mkdir(parents=True, exist_ok=True)
JOBS.mkdir(exist_ok=True)
QUEUE.mkdir(exist_ok=True)
recover_interrupted_jobs()
clear_scene_for_template()
write_state("idle", started_at=now())
LAST_HEARTBEAT = time.monotonic()
atexit.register(mark_stopped)
bpy.app.timers.register(poll_queue, first_interval=0.1, persistent=True)
