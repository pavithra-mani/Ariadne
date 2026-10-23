"""A scripted stand-in for the LLM: lets tests drive the agent loops without any network."""
from typing import Callable

from app.llm.provider import AgentRun, LLMUnavailable, log_call, spend


class FakeLLM:
    name = "fake"

    def __init__(self, json: dict[str, Callable] | None = None, tools: dict[str, list] | None = None, text: str = "findings"):
        self.json = json or {}          # purpose-prefix -> callable(schema, user) -> model instance (or raise LLMUnavailable)
        self.tool_scripts = tools or {}  # purpose -> [(tool_name, kwargs), ...]
        self.text = text
        self.calls: list[str] = []

    def generate_json(self, schema, system, user, purpose, images=None):
        spend(purpose)
        self.calls.append(purpose)
        log_call({"purpose": purpose, "model": "fake", "ms": 1, "tokens_in": 0, "tokens_out": 0, "retries": 0})
        for prefix, fn in self.json.items():
            if purpose.startswith(prefix):
                return fn(schema, user)
        raise LLMUnavailable(f"no scripted response for {purpose}")

    def tool_loop(self, system, user, tools, purpose, max_steps):
        spend(purpose)
        self.calls.append(purpose)
        registry = {fn.__name__: fn for fn in tools}
        run = AgentRun(text=self.text, calls=1)
        for name, kwargs in self.tool_scripts.get(purpose, [])[:max_steps]:
            out = registry[name](**kwargs)
            run.steps.append({"tool": name, "args": kwargs, "result": str(out)[:200]})
            run.calls += 1
        log_call({"purpose": purpose, "model": "fake", "ms": 1, "tokens_in": 0, "tokens_out": 0, "retries": 0})
        return run
