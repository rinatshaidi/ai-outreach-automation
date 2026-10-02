"""Run a minimal secret-safe OpenAI connectivity check from the production app."""

import sys

import httpx

from app.config import get_settings


def main() -> int:
    settings = get_settings()
    configured = settings.openai_api_key is not None
    print(f"OPENAI_API_KEY={'configured' if configured else 'not_configured'}")
    if not configured:
        print("provider=failed reason=not_configured")
        return 1

    key = settings.openai_api_key.get_secret_value()
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": settings.openai_rewrite_model,
                "input": "Return exactly: OK",
                "store": False,
                "max_output_tokens": 16,
            },
            timeout=60,
        )
    except httpx.HTTPError:
        print("provider=failed reason=connection")
        return 1
    finally:
        key = ""

    if 200 <= response.status_code < 300:
        print("provider=working")
        return 0
    if response.status_code in {401, 403}:
        reason = "authentication"
    elif response.status_code == 429:
        reason = "quota_or_rate_limit"
    elif response.status_code == 400:
        reason = "request_rejected"
    elif response.status_code >= 500:
        reason = "provider_temporary"
    else:
        reason = "unexpected_status"
    print(f"provider=failed reason={reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
