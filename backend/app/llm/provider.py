"""LLM access for the agents: one interface, a Gemini implementation, budgets, tracing, fakes for tests.

Design rules
* Every LLM call is optional: any failure (no key, quota, budget, bad output) raises LLMUnavailable and the
  caller falls back to its deterministic path, so the system degrades instead of breaking.
* The model never gets write tools. Tools are read-only and bound to the caller's entity, so the model
  cannot ask for someone else's data or change anything.
* Every call is logged to the incident trace (purpose, model, latency, tokens).
"""
import contextvars
import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

from app.config import settings
from app.observability import traceable

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(Exception):
    """No key, quota exhausted, budget spent, or unusable output: use the deterministic path."""


class BudgetExceeded(LLMUnavailable):
    pass


# ----------------------------------------------------------------------------- per-request context
_budget: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_budget", default=None)
_calls: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_calls", default=None)
stats = {"calls": 0, "ok": 0, "retried": 0, "rate_limited": 0, "failed": 0, "fallbacks": 0, "tokens_in": 0, "tokens_out": 0}


def start_budget(n: int | None = None) -> None:
    """Called once per top-level request; nested (child) incidents share the same budget."""
    if _budget.get() is None:
        _budget.set([settings.llm_budget_per_request if n is None else n])
    if _calls.get() is None:
        _calls.set([])


def reset_budget() -> None:
    """Forget the previous request's budget/call log (worker threads are reused between jobs)."""
    _budget.set(None)
    _calls.set(None)


def spend(purpose: str) -> None:
    b = _budget.get()
    if b is not None:
        if b[0] <= 0:
            raise BudgetExceeded(f"LLM budget spent before '{purpose}'")
        b[0] -= 1


def budget_left() -> int:
    b = _budget.get()
    return b[0] if b is not None else settings.llm_budget_per_request


def log_call(entry: dict) -> None:
    c = _calls.get()
    if c is None:
        c = []
        _calls.set(c)
    c.append(entry)


def take_calls() -> list[dict]:
    """Calls made since the last take (a graph node's slice); resets the log."""
    c = _calls.get()
    if not c:
        return []
    out = list(c)
    c.clear()
    return out


# ----------------------------------------------------------------------------- interface
@dataclass
class AgentRun:
    text: str = ""
    steps: list[dict] = field(default_factory=list)     # [{tool, args, result}] in order
    calls: int = 0


class LLM(Protocol):
    name: str

    def generate_json(self, schema: type[T], system: str, user: str, purpose: str,
                      images: list[tuple[bytes, str]] | None = None) -> T: ...

    def tool_loop(self, system: str, user: str, tools: list[Callable], purpose: str, max_steps: int) -> AgentRun: ...


_override: LLM | None = None
_singleton: LLM | None = None
_lock = threading.Lock()


def set_llm_override(llm: LLM | None) -> None:
    """Tests inject a scripted fake here."""
    global _override
    _override = llm


def get_llm() -> LLM | None:
    if _override is not None:
        return _override
    if not settings.gemini_api_key:
        return None
    global _singleton
    with _lock:
        if _singleton is None:
            _singleton = GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.gemini_rpm)
    return _singleton


def llm_status() -> dict:
    return {"gemini": bool(settings.gemini_api_key) or _override is not None, "model": settings.gemini_model,
            "rpm": settings.gemini_rpm, **stats}


# ----------------------------------------------------------------------------- Gemini
def _retry_delay(err: Exception) -> float | None:
    s = str(err)
    m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s", s) or re.search(r"retry in (\d+(?:\.\d+)?)s", s, re.I)
    return float(m.group(1)) if m else None


class GeminiClient:
    name = "gemini"

    def __init__(self, api_key: str, model: str, rpm: int):
        from google import genai
        self._genai = genai
        from google.genai import types
        # a stalled request must not hold an incident hostage: give up after the timeout and use the rule-based path
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=settings.llm_timeout_s * 1000))
        self.model, self.rpm = model, max(rpm, 1)
        self._window: deque[float] = deque()
        self._open_until, self._fails, self._retry_after = 0.0, 0, 30.0
        self._wlock = threading.Lock()

    # -- rate limiting + retries
    def _gate(self, max_wait: float = 25.0) -> None:
        waited = 0.0
        while True:
            with self._wlock:
                now = time.monotonic()
                while self._window and now - self._window[0] > 60:
                    self._window.popleft()
                if len(self._window) < self.rpm:
                    self._window.append(now)
                    return
                sleep = 60 - (now - self._window[0]) + 0.05
            if waited + sleep > max_wait:
                raise LLMUnavailable("client-side rate limit: waiting would exceed the cap")
            time.sleep(sleep)
            waited += sleep

    def _generate(self, purpose: str, contents, config):
        """One LLM request with fast failure: primary model -> fallback model (separate quota) -> rule-based path.
        Quota/timeouts never make a user wait: after both models fail the circuit opens and later calls skip the
        LLM instantly until it closes again."""
        wait = self._open_until - time.monotonic()
        if wait > 0:
            stats["fallbacks"] += 1
            raise LLMUnavailable(f"{purpose}: LLM paused for {wait:.0f}s after repeated failures; using rule-based path")
        spend(purpose)
        stats["calls"] += 1
        last: Exception | None = None
        for attempt, model in enumerate((self.model, settings.gemini_fallback_model)):
            self._gate()
            t0 = time.perf_counter()
            try:
                resp = _traced_generate(self.client, model, purpose, contents, config)
                ms = round((time.perf_counter() - t0) * 1000)
                usage = getattr(resp, "usage_metadata", None)
                tin, tout = (getattr(usage, "prompt_token_count", 0) or 0), (getattr(usage, "candidates_token_count", 0) or 0)
                stats["ok"] += 1
                stats["tokens_in"] += tin
                stats["tokens_out"] += tout
                log_call({"purpose": purpose, "model": model, "ms": ms, "tokens_in": tin, "tokens_out": tout, "retries": attempt})
                self._fails = 0
                return resp
            except Exception as exc:  # google.genai.errors.APIError, timeout, network...
                last = exc
                if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
                    stats["rate_limited"] += 1
                    self._retry_after = min(max(_retry_delay(exc) or 30.0, 10.0), 120.0)
                if attempt == 0:
                    stats["retried"] += 1  # try the fallback model right away (its quota is separate)
        stats["failed"] += 1
        self._fails += 1
        if getattr(last, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(last):
            self._open_until = time.monotonic() + self._retry_after
        elif self._fails >= 2:
            self._open_until = time.monotonic() + 20.0
        raise LLMUnavailable(f"{purpose}: {type(last).__name__}: {str(last)[:160]}")

    def _thinking(self):
        """Gemini 3.x 'thinks' by default (9-13 s calls); a low level keeps agents responsive. 2.5 models use budgets instead."""
        from google.genai import types
        return types.ThinkingConfig(thinking_level="low") if self.model.startswith("gemini-3") else \
            types.ThinkingConfig(thinking_budget=0) if "2.5" in self.model else None

    # -- structured output
    def generate_json(self, schema, system, user, purpose, images=None):
        from google.genai import types
        parts: list[Any] = [types.Part(text=user)]
        for data, mime in images or []:
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
        cfg = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                          response_schema=schema, temperature=0, thinking_config=self._thinking())
        resp = self._generate(purpose, [types.Content(role="user", parts=parts)], cfg)
        try:
            return schema.model_validate_json(resp.text)
        except Exception as exc:
            stats["failed"] += 1
            raise LLMUnavailable(f"{purpose}: model returned unusable JSON ({str(exc)[:100]})")

    # -- tool-using agent loop (function calling)
    def tool_loop(self, system, user, tools, purpose, max_steps):
        from google.genai import types
        registry = {fn.__name__: fn for fn in tools}
        cfg = types.GenerateContentConfig(system_instruction=system, tools=tools, temperature=0, thinking_config=self._thinking(),
                                          automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        run = AgentRun()
        for step in range(max_steps + 1):
            use_cfg = cfg if step < max_steps else types.GenerateContentConfig(system_instruction=system, temperature=0, thinking_config=self._thinking())
            resp = self._generate(f"{purpose}#{step + 1}", contents, use_cfg)
            run.calls += 1
            if not resp.candidates or not resp.candidates[0].content:
                break
            content = resp.candidates[0].content
            contents.append(content)  # keep the model turn intact (incl. thought signatures)
            calls = [p.function_call for p in (content.parts or []) if p.function_call]
            if not calls:
                run.text = resp.text or ""
                return run
            replies = []
            for fc in calls:
                fn, args = registry.get(fc.name), dict(fc.args or {})
                try:
                    out = _traced_tool(fc.name, fn, args) if fn else {"error": f"unknown tool {fc.name}"}
                except Exception as exc:  # tool errors go back to the model, never crash the run
                    out = {"error": f"{type(exc).__name__}: {exc}"}
                run.steps.append({"tool": fc.name, "args": args, "result": _brief(out)})
                replies.append(types.Part.from_function_response(name=fc.name, response={"result": out}))
            contents.append(types.Content(role="user", parts=replies))
        return run


@traceable(run_type="llm", name="gemini", process_inputs=lambda d: {"model": d["model"], "purpose": d["purpose"]},
           process_outputs=lambda r: {"text": (getattr(r, "text", None) or "")[:500],
                                      "tool_calls": [p.function_call.name for c in (getattr(r, "candidates", None) or [])
                                                     for p in ((c.content.parts if c.content else None) or []) if p.function_call]})
def _traced_generate(client, model, purpose, contents, config):
    return client.models.generate_content(model=model, contents=contents, config=config)


def _traced_tool(name: str, fn: Callable, args: dict):
    return traceable(run_type="tool", name=name)(lambda **kw: fn(**kw))(**args)


def _brief(x: Any, n: int = 220) -> str:
    s = json.dumps(x, default=str)
    return s if len(s) <= n else s[:n] + "…"
