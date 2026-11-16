"""Real Open WebUI -> Ollama -> add-on list -> queued Blender Agent job."""

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_config import ROOT, load, service_url

sys.stdout.reconfigure(encoding="utf-8")
config = load()
base = service_url(config, "webui")
message_id = str(uuid.uuid4())
prompt = (
    "Dùng add-on hoặc operator có sẵn của Blender để tạo một cube kích thước 1.5. "
    "Hãy tự chọn đúng tool, chờ chạy xong và báo đường dẫn file blend kết quả."
)
request = {
    "model": "excel-blender-demo",
    "stream": True,
    "tool_ids": ["excel_blender_demo"],
    "messages": [{"role": "user", "content": prompt}],
    "parent_id": None,
    "id": message_id,
    "user_message": {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": prompt,
        "timestamp": int(time.time()),
    },
}
log_path = ROOT / "logs" / "tool-calls.jsonl"
before = (
    len(log_path.read_text(encoding="utf-8").splitlines()) if log_path.exists() else 0
)
answer = None

with httpx.Client(base_url=base, timeout=300, trust_env=False) as client:
    response = client.post(
        "/api/v1/auths/signin", json={"email": "admin@localhost", "password": "admin"}
    )
    response.raise_for_status()
    client.headers["Authorization"] = "Bearer " + response.json()["token"]
    response = client.post("/api/chat/completions", json=request)
    response.raise_for_status()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        listing = client.get("/api/v1/chats/?page=1").json()
        chats = listing if isinstance(listing, list) else listing.get("items", [])
        for chat in chats[:10]:
            saved = client.get("/api/v1/chats/" + chat["id"]).json()
            message = (
                saved.get("chat", {})
                .get("history", {})
                .get("messages", {})
                .get(message_id)
            )
            if message:
                answer = {"chat_id": chat["id"], "message": message}
                break
        if answer and answer["message"].get("done"):
            break
        time.sleep(2)

calls = [
    json.loads(line)
    for line in log_path.read_text(encoding="utf-8").splitlines()[before:]
    if line
]
listed = next((call for call in calls if call["tool"] == "list_blender_addons"), None)
queued = next(
    (
        call
        for call in calls
        if call["tool"] == "queue_blender_addon"
        and call["arguments"]["operator_id"] == "add_cube"
    ),
    None,
)
completed = next(
    (
        call
        for call in calls
        if call["tool"] == "run_blender_addon"
        and call["arguments"]["operator_id"] == "add_cube"
        and call["result"]["status"] == "completed"
    ),
    None,
)
assert listed and queued and completed
assert completed["result"]["parameters"]["size"] == 1.5
assert completed["result"]["reset_before"]["object_count"] == 0
assert completed["result"]["reset_after"]["object_count"] == 0
assert Path(completed["result"]["output_path"]).is_file()
assert answer and answer["message"].get("done")

(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence" / "webui-agent-smoke.json").write_text(
    json.dumps(
        {"request": request, "answer": answer, "calls": calls},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(
    "PASS: Ollama selected add_cube from the allowlist and completed it through the queued Blender Agent."
)
print(base + "/c/" + answer["chat_id"])
print(completed["result"]["output_path"])
