"""Print only response structure for a safe, non-personal OpenAI discovery check."""

from __future__ import annotations

import asyncio

import httpx

from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    assert settings.openai_api_key is not None
    payload = {
        "model": settings.openai_rewrite_model,
        "store": False,
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
        "input": "Find one real AI company in Russia. Return a short answer.",
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}"},
            json=payload,
        )
    data = response.json()
    print(f"status={response.status_code}")
    print(f"top_keys={','.join(sorted(data.keys()))}")
    print(f"response_status={data.get('status', '')}")
    print(f"error_code={(data.get('error') or {}).get('code', '')}")
    print(f"output_types={','.join(str(item.get('type', '')) for item in data.get('output', []))}")
    print(
        "content_types=" + ",".join(
            str(content.get("type", ""))
            for item in data.get("output", [])
            for content in item.get("content", [])
        )
    )


asyncio.run(main())
