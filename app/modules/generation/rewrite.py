"""Real-provider AI rewrite boundary; fail closed when no provider is configured."""

import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.modules.generation.service import GenerationContext


class AIRewriteUnavailable(RuntimeError):
    pass


class AIRewriteFailed(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RewrittenMessage:
    subject: str
    body: str


class AIRewriteProvider(Protocol):
    provider_name: str
    model_name: str

    async def rewrite(
        self,
        *,
        context: GenerationContext,
        subject: str,
        body: str,
        instruction: str,
        message_format: str = "expanded",
        tone: str = "professional",
    ) -> RewrittenMessage: ...


class UnavailableAIRewriteProvider:
    provider_name = "unavailable"
    model_name = "none"

    async def rewrite(
        self,
        *,
        context: GenerationContext,
        subject: str,
        body: str,
        instruction: str,
        message_format: str = "expanded",
        tone: str = "professional",
    ) -> RewrittenMessage:
        del context, subject, body, instruction, message_format, tone
        raise AIRewriteUnavailable(
            "AI rewrite is not configured. Set AI_REWRITE_PROVIDER=openai and provide "
            "OPENAI_API_KEY; no revision was created."
        )


class OpenAIRewriteProvider:
    provider_name = "openai-responses"

    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise AIRewriteUnavailable("OPENAI_API_KEY is not configured")
        self.api_key = settings.openai_api_key.get_secret_value()
        self.model_name = settings.openai_rewrite_model

    async def rewrite(
        self,
        *,
        context: GenerationContext,
        subject: str,
        body: str,
        instruction: str,
        message_format: str = "expanded",
        tone: str = "professional",
    ) -> RewrittenMessage:
        voice = context.sender_voice_profile
        prompt_context = {
            "user_instruction": instruction,
            "current_draft": {"subject": subject, "body": body},
            "sender_name": context.sender_name,
            "sender_voice": {
                "communication_style": voice.communication_style if voice else [],
                "values": voice.values if voice else [],
                "motivations": voice.motivations if voice else [],
                "interests": voice.interests if voice else [],
                "preferred_tone": voice.preferred_tone if voice else "",
                "things_to_avoid": voice.things_to_avoid if voice else [],
            },
            "candidate_facts": [
                item.text for item in context.candidate_facts if item.use_for_ai_analysis
            ],
            "company": context.company.name,
            "company_facts": [item.value for item in context.company_facts],
            "recipient": {"name": context.contact.name, "role": context.contact.role},
            "approved_style_examples": [
                item.text for item in context.approved_examples if item.approved
            ],
            "language": context.language.code,
            "message_format": message_format,
            "tone": tone,
        }
        payload = {
            "model": self.model_name,
            "store": False,
            "instructions": (
                "Rewrite the outreach message following the owner's instruction. Preserve only "
                "facts supplied in the context. Keep the sender's honest seniority and voice. "
                "Do not add internal-system language, unsupported claims, or delivery actions. "
                "For message_format=short, return 25-90 words and keep the subject as an internal "
                "label. For message_format=expanded, return a complete email. Respect tone as "
                "professional or friendly without exaggeration or artificial familiarity. "
                "Return only the requested JSON object."
            ),
            "input": json.dumps(prompt_context, ensure_ascii=False),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "rewritten_outreach_email",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["subject", "body"],
                        "additionalProperties": False,
                    },
                }
            },
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
            if response.status_code in {401, 403}:
                raise AIRewriteFailed(
                    "ai_provider_auth_failed",
                    "OpenAI rejected the API key. Replace the production secret.",
                )
            if response.status_code == 429:
                raise AIRewriteFailed(
                    "ai_provider_limit_reached",
                    "OpenAI rate limit, quota, or billing limit was reached.",
                )
            if response.status_code == 400:
                raise AIRewriteFailed(
                    "ai_provider_request_rejected",
                    "OpenAI rejected the rewrite request configuration.",
                )
            if response.status_code >= 500:
                raise AIRewriteFailed(
                    "ai_provider_temporarily_unavailable",
                    "OpenAI is temporarily unavailable. Try again later.",
                )
            response.raise_for_status()
            response_payload = response.json()
            output_text = "".join(
                content.get("text", "")
                for item in response_payload.get("output", [])
                for content in item.get("content", [])
                if content.get("type") == "output_text"
            )
            parsed = json.loads(output_text)
            rewritten = RewrittenMessage(
                subject=str(parsed["subject"]).strip(),
                body=str(parsed["body"]).strip(),
            )
        except AIRewriteFailed:
            raise
        except httpx.HTTPError as exc:
            raise AIRewriteFailed(
                "ai_provider_connection_failed",
                "Could not safely connect to OpenAI. No revision was created.",
            ) from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIRewriteFailed(
                "ai_provider_invalid_response",
                "OpenAI returned an invalid rewrite response. No revision was created.",
            ) from exc
        if not rewritten.subject or not rewritten.body:
            raise AIRewriteFailed(
                "ai_provider_invalid_response",
                "OpenAI returned an empty rewrite. No revision was created.",
            )
        return rewritten


def get_ai_rewrite_provider() -> AIRewriteProvider:
    settings = get_settings()
    if settings.ai_rewrite_provider == "openai":
        return OpenAIRewriteProvider(settings)
    return UnavailableAIRewriteProvider()
