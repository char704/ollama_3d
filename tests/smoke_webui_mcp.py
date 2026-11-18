"""Real Qwen -> Open WebUI -> MCP selection and execution smoke test."""

import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_config import ROOT, load, service_url

sys.stdout.reconfigure(encoding="utf-8")
CONFIG = load()
AUDIT = ROOT / "logs" / "mcp-tool-calls.jsonl"
MODEL = "excel-blender-mcp-proof"
TOOL_SERVER = "server:mcp:" + CONFIG["mcp"]["server_id"]


def audit_records():
    if not AUDIT.exists():
        return []
    return [json.loads(line) for line in AUDIT.read_text(encoding="utf-8").splitlines() if line]


def send_chat(client, prompt):
    message_id = str(uuid.uuid4())
    body = {
        "model": MODEL,
        "stream": True,
        "tool_ids": [TOOL_SERVER],
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
    response = client.post("/api/chat/completions", json=body)
    response.raise_for_status()
    return body, response.text


def main():
    base = service_url(CONFIG, "webui")
    evidence = []
    with httpx.Client(base_url=base, timeout=300, trust_env=False) as client:
        login = client.post(
            "/api/v1/auths/signin",
            json={"email": "admin@localhost", "password": "admin"},
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["token"]

        cases = [
            (
                "status",
                "Hệ thống Excel VBA và Blender add-on đã sẵn sàng chưa? Hãy kiểm tra thật.",
                "system_status",
            ),
            (
                "explanation",
                "Giải thích ngắn gọn MCP là gì, không chạy xử lý và không kiểm tra hệ thống.",
                None,
            ),
            (
                "missing_paths",
                "Hãy chạy Excel sang Blender cho tôi, nhưng tôi chưa cung cấp đường dẫn.",
                None,
            ),
            (
                "processing",
                "Chạy xử lý thật với excel_path='{}', model_path='{}', output_dir='{}'.",
                "run_excel_to_blender",
            ),
            (
                "colored_cube",
                "Tạo một cube màu tím #7C3AED, kích thước 2.5, tên QwenPurpleCube và lưu vào output_dir='{}'.",
                "create_colored_primitive",
            ),
        ]
        excel = (ROOT / "inputs" / "Footwear_BOM.xlsx").resolve()
        model = (ROOT / "inputs" / "Sneaker_Unassigned.blend").resolve()
        output = (ROOT / "outputs").resolve()

        for name, prompt, expected in cases:
            if name == "processing":
                prompt = prompt.format(excel, model, output)
            if name == "colored_cube":
                prompt = prompt.format(output)
            before = audit_records()
            request, response_text = send_chat(client, prompt)
            after = audit_records()
            new_calls = after[len(before) :]
            tools = [call["tool"] for call in new_calls]
            if expected is None:
                assert not tools, f"{name}: unexpected MCP calls {tools}"
            else:
                assert tools == [expected], f"{name}: expected {expected}, got {tools}"
            if name == "status":
                assert new_calls[0]["result"]["ready"] is True
            if name == "processing":
                result = new_calls[0]["result"]
                assert result["status"] == "completed"
                assert Path(result["output_path"]).is_file()
            if name == "colored_cube":
                result = new_calls[0]["result"]
                assert result["status"] == "completed"
                assert result["primitive"] == "cube"
                assert result["color_hex"] == "#7C3AED"
                assert Path(result["output_path"]).is_file()
            evidence.append(
                {
                    "case": name,
                    "request": request,
                    "mcp_calls": new_calls,
                    "response_tail": response_text[-4000:],
                }
            )
            print(f"{name}: calls={tools}", flush=True)

    (ROOT / "evidence").mkdir(exist_ok=True)
    path = ROOT / "evidence" / "webui-mcp-smoke.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: Qwen selected and executed only the intended MCP tools. Evidence: {path}")


if __name__ == "__main__":
    main()
