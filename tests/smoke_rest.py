"""Live smoke test for the OpenAI-compatible local REST agent."""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_config import ROOT, load, service_url

CONFIG = load()
BASE = service_url(CONFIG, "api")
HEADERS = {"Authorization": "Bearer ollama3d-local"}


def main():
    health = httpx.get(BASE + "/health", timeout=10, trust_env=False)
    health.raise_for_status()
    assert health.json()["transport"] == "rest-direct"

    models = httpx.get(BASE + "/v1/models", headers=HEADERS, timeout=10, trust_env=False)
    models.raise_for_status()
    assert any(item["id"] == "ollama3d-direct" for item in models.json()["data"])

    response = httpx.post(
        BASE + "/v1/chat/completions",
        headers=HEADERS,
        json={
            "model": "ollama3d-direct",
            "messages": [{"role": "user", "content": "Chỉ chào tôi một câu ngắn."}],
            "stream": False,
        },
        timeout=180,
        trust_env=False,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    assert isinstance(content, str) and content.strip()
    evidence = ROOT / "evidence" / "rest-smoke.json"
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(
        json.dumps(
            {"ok": True, "health": health.json(), "model": "ollama3d-direct", "content": content},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"PASS: direct REST agent replied. Evidence: {evidence}")


if __name__ == "__main__":
    main()
