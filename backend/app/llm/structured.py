"""Groq-backed structuring of agent outputs.

Groq's only job (per the design) is to turn verified facts into schema-valid JSON prose.
Without GROQ_API_KEY - or on any failure after one repair retry - a deterministic template
fallback is used, so the system always returns valid structured output.
`locked` fields are enforced from the facts after generation: the model cannot flip decisions.
"""
import json
import time
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

T = TypeVar("T", bound=BaseModel)

SYSTEM = (
    "You are the response formatter for Ariadne, a sericulture supply-chain assistant. "
    "You receive VERIFIED FACTS as JSON. Write the requested JSON object using ONLY those facts. "
    "Never invent numbers, diseases, names or advice that is not in the facts. Keep sentences short and "
    "plain, suitable for a farmer or mill operator. Return only a JSON object matching the schema."
)

_client = None
stats = {"calls": 0, "groq_ok": 0, "repaired": 0, "fallback": 0}


def groq_enabled() -> bool:
    return bool(settings.groq_api_key)


def _get_client():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=settings.groq_api_key, timeout=20)
    return _client


def _call(messages: list[dict]) -> str:
    r = _get_client().chat.completions.create(
        model=settings.groq_model, messages=messages, temperature=0,
        response_format={"type": "json_object"})
    return r.choices[0].message.content


def structure(schema: type[T], task: str, facts: dict, fallback: Callable[[], T],
              locked: dict | None = None) -> tuple[T, str]:
    """Return (validated_output, producer) where producer is 'groq' | 'groq_repaired' | 'template'."""
    stats["calls"] += 1
    if groq_enabled():
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Task: {task}\nSchema: {json.dumps(schema.model_json_schema())}\n"
                                        f"FACTS: {json.dumps(facts, default=str)}"},
        ]
        raw = ""
        for attempt in range(2):
            try:
                raw = _call(messages)
                out = schema.model_validate_json(raw)
                if locked:
                    out = out.model_copy(update=locked)
                stats["groq_ok" if attempt == 0 else "repaired"] += 1
                return out, "groq" if attempt == 0 else "groq_repaired"
            except (ValidationError, json.JSONDecodeError) as exc:
                messages += [{"role": "assistant", "content": raw or "{}"},
                             {"role": "user", "content": f"Invalid: {str(exc)[:300]}. Return corrected JSON only."}]
            except Exception:  # network / auth / rate limit
                time.sleep(0.2)
                break
    stats["fallback"] += 1
    out = fallback()
    return (out.model_copy(update=locked) if locked else out), "template"
