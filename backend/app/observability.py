"""LangSmith switch + span helpers.

A LangSmith key turns tracing on (it overrides LANGSMITH_TRACING=false from .env/docker, which is the shipped
default). `traceable` is langsmith's decorator, or a no-op if the package is missing; with tracing off it costs
nothing, so the local per-incident trace stays the always-on record.
"""
import os

from dotenv import dotenv_values

from app.config import settings


def configure() -> bool:
    if not settings.langsmith_api_key:
        return False
    for path in settings.model_config["env_file"]:  # pass the other LANGSMITH_* lines (agent id, endpoint, project) to the SDK
        for k, v in dotenv_values(path).items():
            if k.startswith("LANGSMITH_") and v:
                os.environ.setdefault(k, v)
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_TRACING"] = "true"
    if not os.environ.get("LANGSMITH_AGENT_ID"):  # the SDK rejects a project and an agent address set together
        os.environ.setdefault("LANGSMITH_PROJECT", "ariadne")
    else:
        os.environ.pop("LANGSMITH_PROJECT", None)
    return True


try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*_a, **_k):
        return lambda fn: fn

enabled = configure()
