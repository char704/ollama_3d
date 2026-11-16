"""Real Open WebUI -> Ollama native tool loop -> Excel API -> Blender API."""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
import time
import uuid
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_config import ROOT, load, data_path, service_url
from adapters.excel import read_bom

config = load()
assert all(
    item["provider"] == "local" for item in config["workflow"].values()
), "This smoke test requires local workflow providers"
base = service_url(config, "webui")
source = data_path(config, "inputs") / "Footwear_BOM.xlsx"
expected = read_bom(source)
message_id = str(uuid.uuid4())
prompt = "Dùng Footwear_BOM.xlsx, xuất VBOM rồi áp vật liệu và màu vào model mặc định. Dùng thư mục lưu mặc định. Chạy nền, không mở cửa sổ Blender. Hoàn tất rồi báo đường dẫn kết quả."
body = {
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
logfile = ROOT / "logs/tool-calls.jsonl"
before = (
    len(logfile.read_text(encoding="utf-8").splitlines()) if logfile.exists() else 0
)
answer = None
with httpx.Client(base_url=base, timeout=300, trust_env=False) as client:
    response = client.post(
        "/api/v1/auths/signin", json={"email": "admin@localhost", "password": "admin"}
    )
    response.raise_for_status()
    client.headers["Authorization"] = "Bearer " + response.json()["token"]
    print("Running a real Ollama tool-calling chat...", flush=True)
    response = client.post("/api/chat/completions", json=body)
    response.raise_for_status()
    try:
        answer = response.json()
    except ValueError:
        pass
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        listing = client.get("/api/v1/chats/?page=1")
        listing.raise_for_status()
        chats = listing.json()
        chats = chats if isinstance(chats, list) else chats.get("items", [])
        for chat in chats[:10]:
            saved = client.get("/api/v1/chats/" + chat["id"])
            saved.raise_for_status()
            message = (
                saved.json()
                .get("chat", {})
                .get("history", {})
                .get("messages", {})
                .get(message_id)
            )
            if message:
                answer = {"chat_id": chat["id"], "message": message}
                break
        if answer and answer.get("message", {}).get("done"):
            break
        time.sleep(2)
calls = [
    json.loads(line)
    for line in logfile.read_text(encoding="utf-8").splitlines()[before:]
    if line
]
(ROOT / "evidence").mkdir(exist_ok=True)
(ROOT / "evidence/webui-api-smoke.json").write_text(
    json.dumps(
        {"request": body, "answer": answer, "calls": calls},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
exported = next(
    (
        c["result"]
        for c in calls
        if c["tool"] == "export_excel_to_vbom"
        and c["result"]["source_excel"] == str(source)
    ),
    None,
)
assert exported, "No actual Excel export; see evidence/webui-api-smoke.json"
applied = next(
    (
        c["result"]
        for c in calls
        if c["tool"] == "apply_vbom_in_blender"
        and c["result"]["run_id"] == exported["run_id"]
    ),
    None,
)
assert (
    applied
    and applied["status"] == "completed"
    and applied["verified_after_reopen"]
    and not applied["window_opened"]
)
assert (
    Path(applied["output"]).is_relative_to(data_path(config, "outputs"))
    and Path(applied["output"]).is_file()
)
assert [r["color"] for r in applied["applied"]] == [r["color"] for r in expected]
assert answer and answer["message"].get("done"), "Chat did not finish"
print(
    "PASS: actual Ollama tool calls, correct workbook/colors/default paths, saved Blender verified.",
    flush=True,
)
print(base + "/c/" + answer["chat_id"], flush=True)
print(applied["output"], flush=True)
