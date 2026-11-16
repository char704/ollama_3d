"""Allowlisted Blender operators, persistent services, and the queued Blender Agent."""

import datetime
import hashlib
import subprocess
import threading
import time
import uuid
from pathlib import Path

import psutil

from project_config import CONFIG_FILE, data_path
from .common import (
    BLENDER,
    CONFIG,
    DEFAULT_MODEL,
    ROOT,
    log,
    read_json,
    scoped_path,
    write_json,
)

AGENT_ROOT = ROOT / "runtime" / "blender-agent"
AGENT_JOBS = AGENT_ROOT / "jobs"
AGENT_QUEUE = AGENT_ROOT / "queue"
AGENT_STATE = AGENT_ROOT / "state.json"
AGENT_STOP = AGENT_ROOT / "stop.request.json"
OPERATOR_CALLS = ROOT / "runtime" / "operator-calls"
OPERATOR_PROCESSES = ROOT / "runtime" / "operator-processes.json"
_lock = threading.Lock()
_queue_lock = threading.Lock()
_persistent_lock = threading.Lock()


def _now():
    return datetime.datetime.now().astimezone().isoformat()


def _agent_fingerprint():
    paths = [
        CONFIG_FILE,
        ROOT / "project_config.py",
        ROOT / "tool_registry.py",
        ROOT / "adapters" / "operators.py",
        ROOT / "blender" / "agent_runtime.py",
        *sorted((ROOT / "tool-library").rglob("*.json")),
    ]
    return hashlib.sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()


def _configured(operator_id=None, include_hidden=True):
    items = [
        item
        for item in CONFIG.get("blender_operators", [])
        if item.get("enabled", True)
    ]
    if not include_hidden:
        items = [item for item in items if item.get("exposed_to_model", True)]
    if operator_id is None:
        return items
    item = next((item for item in items if item["id"] == operator_id), None)
    if item is None:
        raise ValueError("Unknown or disabled Blender operator: " + operator_id)
    return item


def list_operators():
    operators = []
    for item in _configured(include_hidden=False):
        operators.append(
            {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "operator": item["operator"],
                "execution_mode": item["execution_mode"],
                "load_model": bool(item.get("load_model")),
                "save_after": bool(item.get("save_after")),
                "parameters": item.get("parameters", {}),
            }
        )
    result = {
        "ok": True,
        "operators": operators,
        "usage": "Choose the operator whose description matches the request, then call run_blender_addon with its exact id and only documented parameters.",
    }
    log("list_blender_addons", {"result": result})
    return result


def _valid_value(name, value, spec):
    kind = spec["type"]
    valid = (
        (kind == "string" and isinstance(value, str))
        or (kind == "integer" and type(value) is int)
        or (kind == "number" and type(value) in (int, float))
        or (kind == "boolean" and type(value) is bool)
    )
    if not valid:
        raise ValueError(f"Parameter {name} must be {kind}")
    if kind == "string" and len(value) > 4096:
        raise ValueError(f"Parameter {name} is too long")
    if "enum" in spec and value not in spec["enum"]:
        raise ValueError(f'Parameter {name} must be one of {spec["enum"]}')
    if "minimum" in spec and value < spec["minimum"]:
        raise ValueError(f'Parameter {name} must be at least {spec["minimum"]}')
    if "maximum" in spec and value > spec["maximum"]:
        raise ValueError(f'Parameter {name} must be at most {spec["maximum"]}')
    return value


def _parameters(item, supplied):
    if not isinstance(supplied, dict):
        raise ValueError("parameters must be a JSON object")
    specs = item.get("parameters", {})
    unknown = sorted(set(supplied) - set(specs))
    if unknown:
        raise ValueError("Unknown parameters: " + ", ".join(unknown))
    result = {}
    for name, spec in specs.items():
        if name in supplied:
            value = supplied[name]
        elif "default" in spec:
            value = spec["default"]
        elif spec.get("required"):
            raise ValueError("Missing required parameter: " + name)
        else:
            continue
        result[name] = _valid_value(name, value, spec)
    return result


def _verified_process(state, script_name):
    try:
        process = psutil.Process(state["pid"])
        if abs(process.create_time() - state["create_time"]) > 1:
            return None
        if Path(process.exe()).resolve() != BLENDER.resolve():
            return None
        if not any(
            Path(argument).name == script_name for argument in process.cmdline()
        ):
            return None
        return process
    except (psutil.Error, OSError, KeyError):
        return None


def _terminate_process(process):
    process.terminate()
    try:
        process.wait(10)
    except (psutil.TimeoutExpired, subprocess.TimeoutExpired):
        process.kill()
        process.wait(10)


def _job_runtime(job):
    started = job.get("started_at")
    if not started:
        return 0.0
    try:
        value = datetime.datetime.fromisoformat(started)
        return max(0.0, (datetime.datetime.now().astimezone() - value).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def _mark_job_interrupted(job_id, error):
    if not job_id:
        return
    path = AGENT_JOBS / (job_id + ".json")
    if not path.is_file():
        return
    job = read_json(path)
    if job.get("status") not in ("queued", "running"):
        return
    job.update(ok=False, status="interrupted", finished_at=_now(), error=error)
    write_json(path, job)
    (AGENT_QUEUE / (job_id + ".json")).unlink(missing_ok=True)


def agent_status():
    if not AGENT_STATE.is_file():
        return {"ok": True, "ready": False, "status": "stopped"}
    state = read_json(AGENT_STATE)
    process = _verified_process(state, "agent_runtime.py")
    if process is None:
        return {**state, "ok": True, "ready": False, "status": "stopped"}
    heartbeat_age = max(0.0, time.time() - AGENT_STATE.stat().st_mtime)
    busy = state.get("status") == "busy"
    current_job = None
    runtime = 0.0
    execution_limit = 0.0
    if busy and state.get("current_job"):
        job_path = AGENT_JOBS / (state["current_job"] + ".json")
        if job_path.is_file():
            current_job = read_json(job_path)
            runtime = _job_runtime(current_job)
            execution_limit = float(
                current_job.get(
                    "execution_timeout_seconds",
                    CONFIG["blender_agent"]["job_timeout_seconds"],
                )
            ) + float(CONFIG["blender_agent"]["hung_grace_seconds"])
    heartbeat_limit = max(
        5.0, CONFIG["blender_agent"]["heartbeat_interval_seconds"] * 5
    )
    heartbeat_fresh = heartbeat_age <= heartbeat_limit
    busy_within_deadline = (
        busy and current_job is not None and runtime <= execution_limit
    )
    responsive = heartbeat_fresh or busy_within_deadline
    current_version = state.get("fingerprint") == _agent_fingerprint()
    ready = responsive and current_version
    return {
        **state,
        "ok": True,
        "ready": ready,
        "process_alive": True,
        "current_version": current_version,
        "responsive": responsive,
        "unresponsive": not responsive,
        "job_runtime_seconds": round(runtime, 3) if busy else None,
        "job_execution_limit_seconds": execution_limit if busy else None,
        "heartbeat_age_seconds": round(heartbeat_age, 3),
    }


def ensure_agent():
    if not CONFIG["blender_agent"]["enabled"]:
        raise RuntimeError("Blender Agent is disabled in config.json")
    with _lock:
        status = agent_status()
        if status.get("ready"):
            return status
        stale_process = _verified_process(status, "agent_runtime.py")
        if stale_process:
            if status.get("current_job") and not status.get("unresponsive"):
                raise RuntimeError(
                    "Blender Agent must not restart while a healthy job is running"
                )
            if (
                status.get("current_job")
                and not CONFIG["blender_agent"]["auto_restart_hung"]
            ):
                raise RuntimeError(
                    "Blender Agent exceeded its execution deadline; automatic restart is disabled"
                )
            interrupted_job = status.get("current_job")
            _terminate_process(stale_process)
            _mark_job_interrupted(
                interrupted_job,
                "Blender Agent exceeded its execution deadline and was restarted.",
            )
        AGENT_ROOT.mkdir(parents=True, exist_ok=True)
        AGENT_JOBS.mkdir(exist_ok=True)
        AGENT_QUEUE.mkdir(exist_ok=True)
        AGENT_STATE.unlink(missing_ok=True)
        AGENT_STOP.unlink(missing_ok=True)
        bootstrap = AGENT_ROOT / ("bootstrap-" + uuid.uuid4().hex + ".json")
        log_path = ROOT / "logs" / "blender-agent.log"
        log_path.parent.mkdir(exist_ok=True)
        stream = log_path.open("a", encoding="utf-8")
        command = [
            str(BLENDER),
            "--python",
            str(ROOT / "blender" / "agent_runtime.py"),
            "--",
            str(ROOT),
            str(CONFIG_FILE),
            str(bootstrap),
        ]
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT
        )
        stream.close()
        write_json(
            bootstrap,
            {
                "pid": process.pid,
                "create_time": psutil.Process(process.pid).create_time(),
                "fingerprint": _agent_fingerprint(),
            },
        )
        deadline = time.monotonic() + CONFIG["blender_agent"]["startup_timeout_seconds"]
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "Blender Agent exited during startup. See " + str(log_path)
                )
            status = agent_status()
            if status.get("ready") and status.get("pid") == process.pid:
                return status
            time.sleep(0.25)
        _terminate_process(process)
        raise RuntimeError("Blender Agent startup timed out. See " + str(log_path))


def stop_agent():
    status = agent_status()
    process = _verified_process(status, "agent_runtime.py")
    if process is None:
        return {"ok": True, "status": "stopped"}
    if status.get("current_job"):
        raise RuntimeError(
            "Blender Agent is processing a job. Wait before stopping it."
        )
    write_json(AGENT_STOP, {"requested_at": _now(), "pid": process.pid})
    try:
        process.wait(10)
    except psutil.TimeoutExpired:
        _terminate_process(process)
    return {"ok": True, "status": "stopped", "pid": process.pid}


def get_agent_job(job_id):
    if (
        not isinstance(job_id, str)
        or len(job_id) != 32
        or any(c not in "0123456789abcdef" for c in job_id)
    ):
        raise ValueError("Invalid Blender Agent job_id")
    path = AGENT_JOBS / (job_id + ".json")
    if not path.is_file():
        raise FileNotFoundError("Blender Agent job not found")
    return read_json(path)


def cancel_agent_job(job_id):
    with _queue_lock:
        job = get_agent_job(job_id)
        if job.get("status") != "queued":
            if job.get("status") in ("completed", "failed", "cancelled", "interrupted"):
                return {**job, "already_terminal": True}
            raise RuntimeError("Only a queued Blender Agent job can be cancelled")
        marker = AGENT_QUEUE / (job_id + ".json")
        if not marker.is_file():
            raise RuntimeError("Blender Agent is already claiming this job")
        job.update(
            ok=False,
            status="cancelled",
            finished_at=_now(),
            error="Cancelled before Blender execution.",
        )
        write_json(AGENT_JOBS / (job_id + ".json"), job)
        marker.unlink(missing_ok=True)
        log("cancel_blender_job", {"arguments": {"job_id": job_id}, "result": job})
        return job


def _wait_for_job(job_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = get_agent_job(job_id)
        if job["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return job
        time.sleep(0.2)
    job = get_agent_job(job_id)
    return {
        **job,
        "ok": False,
        "wait_timeout": True,
        "error": "The job is still running. Use get_blender_job with this job_id.",
    }


def _submit_agent_job(item, parameters, model, wait_for_completion):
    agent = ensure_agent()
    with _queue_lock:
        queued = 0
        for marker in AGENT_QUEUE.glob("*.json"):
            try:
                queued_job = get_agent_job(marker.stem)
            except (FileNotFoundError, ValueError, KeyError):
                continue
            if queued_job.get("status") == "queued":
                queued += 1
        if queued >= CONFIG["blender_agent"]["max_queued_jobs"]:
            raise RuntimeError("Blender Agent queue is full; wait for an existing job")
        job_id = uuid.uuid4().hex
        output_dir = data_path(CONFIG, "outputs") / "agent" / job_id
        output_dir.mkdir(parents=True, exist_ok=False)
        job = {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "created_at": _now(),
            "operator_id": item["id"],
            "operator": item["operator"],
            "parameters": parameters,
            "model_path": str(model) if model else "",
            "output_path": (
                str(output_dir / "result.blend") if item.get("save_after") else ""
            ),
            "execution_timeout_seconds": min(
                item.get("timeout_seconds", 30),
                CONFIG["blender_agent"]["job_timeout_seconds"],
            ),
            "agent_instance_id": agent.get("instance_id"),
        }
        write_json(AGENT_JOBS / (job_id + ".json"), job)
        write_json(
            AGENT_QUEUE / (job_id + ".json"),
            {"job_id": job_id, "created_at": job["created_at"]},
        )
    log(
        "queue_blender_addon",
        {
            "arguments": {"operator_id": item["id"], "parameters": parameters},
            "result": job,
        },
    )
    if not wait_for_completion:
        return job
    return _wait_for_job(
        job_id,
        min(
            item.get("timeout_seconds", 30) + 15,
            CONFIG["blender_agent"]["job_timeout_seconds"],
        ),
    )


def _persistent_running(operator_id):
    if not OPERATOR_PROCESSES.is_file():
        return None
    state = read_json(OPERATOR_PROCESSES).get(operator_id)
    return state if state and _verified_process(state, "run_operator.py") else None


def _remember_persistent(operator_id, process, result):
    state = read_json(OPERATOR_PROCESSES) if OPERATOR_PROCESSES.is_file() else {}
    state[operator_id] = {
        "pid": process.pid,
        "create_time": psutil.Process(process.pid).create_time(),
        "status": "running",
        "operator": result["operator"],
        "parameters": result["parameters"],
    }
    write_json(OPERATOR_PROCESSES, state)
    return state[operator_id]


def _run_persistent(item, parameters, model):
    running = _persistent_running(item["id"])
    if running:
        return {
            "ok": True,
            "status": "already_running",
            "operator_id": item["id"],
            "pid": running["pid"],
            "operator": item["operator"],
            "parameters": running["parameters"],
        }
    request_id = uuid.uuid4().hex
    OPERATOR_CALLS.mkdir(parents=True, exist_ok=True)
    request_file = OPERATOR_CALLS / (request_id + ".request.json")
    report_file = OPERATOR_CALLS / (request_id + ".result.json")
    write_json(
        request_file,
        {
            "operator_id": item["id"],
            "operator": item["operator"],
            "parameters": parameters,
            "execution_mode": "persistent",
            "save_after": bool(item.get("save_after")),
        },
    )
    command = [str(BLENDER)]
    if model:
        command.append(str(model))
    command += [
        "--python-exit-code",
        "1",
        "--python",
        str(ROOT / "blender/run_operator.py"),
        "--",
        str(request_file),
        str(report_file),
    ]
    log_path = ROOT / "logs" / ("operator-" + item["id"] + ".log")
    log_path.parent.mkdir(exist_ok=True)
    stream = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
    stream.close()
    deadline = time.monotonic() + item.get("timeout_seconds", 30)
    while time.monotonic() < deadline and not report_file.is_file():
        if process.poll() is not None:
            break
        time.sleep(0.25)
    if not report_file.is_file():
        raise RuntimeError("Blender did not confirm the operator. See " + str(log_path))
    result = read_json(report_file)
    if not result.get("ok"):
        raise RuntimeError(
            result.get("error", "Blender operator failed") + ". See " + str(log_path)
        )
    result.update(
        operator_id=item["id"],
        request_id=request_id,
        model_path=str(model) if model else "",
    )
    result.update(_remember_persistent(item["id"], process, result))
    return result


def run_operator(
    operator_id,
    parameters=None,
    model_path="",
    wait_for_completion=True,
    internal=False,
):
    item = _configured(operator_id, include_hidden=internal)
    parameters = _parameters(item, parameters or {})
    if not BLENDER.is_file():
        raise FileNotFoundError("Blender executable not found: " + str(BLENDER))
    model = None
    if item.get("load_model"):
        model = scoped_path(model_path, DEFAULT_MODEL)
        if model.suffix.lower() != ".blend" or not model.is_file():
            raise ValueError("Choose an existing Blender model")
    if item["execution_mode"] == "persistent":
        with _persistent_lock:
            result = _run_persistent(item, parameters, model)
    else:
        result = _submit_agent_job(item, parameters, model, wait_for_completion)
    log(
        "run_blender_addon",
        {
            "arguments": {
                "operator_id": operator_id,
                "parameters": parameters,
                "model_path": str(model) if model else "",
            },
            "result": result,
        },
    )
    return result
