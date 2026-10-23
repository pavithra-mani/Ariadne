"""The tool-using advisor agent: investigates with read-only tools, then writes a schema-valid, grounded answer.

Flow: (1) tool loop - the model decides what to look up (knowledge base, stock, outlook, partners, history);
(2) one structured call turns its findings into the output schema; (3) deterministic guards: citations must
refer to passages actually retrieved, decision fields stay locked, and steps that are not supported by evidence
are flagged instead of presented as knowledge-base facts.
"""
import json

from pydantic import BaseModel

from app.agents.tools import ToolContext, build_tools
from app.config import settings
from app.llm.provider import AgentRun, LLMUnavailable, budget_left, get_llm
from app.llm.schemas import Advisory, AnswerOut
from app.llm.structured import SYSTEM as FORMAT_SYSTEM, structure
from app.rag.agentic import overlap

ROLE_NAME = {"mulberry_farm": "mulberry farmer", "silkworm_farm": "silkworm farmer", "reeler": "reeler", "spinner": "spinner / throwster"}

AGENT_SYSTEM = """You are Ariadne's advisor agent for a {role} in a sericulture supply chain.
You have read-only tools. Rules:
- Use search_knowledge to find guidance; never state disease treatments, chemicals, doses or storage rules from memory.
- Use get_my_stock / get_supply_outlook when the question depends on the user's own numbers. Numbers come only from tools or the given FACTS.
- If search_knowledge returns nothing relevant, say you cannot answer from the knowledge base. Do not guess.
- Be brief: at most {steps} tool calls, then stop and write your findings in plain text, listing the passage refs you rely on."""

FINAL_SYSTEM = (FORMAT_SYSTEM + " Cite knowledge-base passages by their ref numbers in `citations`. "
                "A mitigation step or key point that comes from a passage must be supported by that passage; "
                "steps that come from FACTS need no citation. Never invent chemicals, doses or numbers.")


def _grounding(steps: list[str], evidence: list[str], facts_text: str) -> list[int]:
    """Indexes of steps that neither overlap a retrieved passage nor the verified facts."""
    corpus = evidence + [facts_text]
    return [i for i, s in enumerate(steps) if max((overlap(s, c) for c in corpus), default=0) < 0.3]


def produce(state: dict, schema: type[BaseModel], task: str, facts: dict, fallback, locked: dict | None = None,
            agent_locked: dict | None = None):
    """Return (output, producer, meta). Agentic when an LLM is available, a human asked (not an auto-opened
    child incident) and the call budget allows; otherwise the formatter path (Groq/Gemini/template)."""
    llm = get_llm()
    agentic = llm is not None and state.get("user_id") is not None and budget_left() >= 2
    if agentic:
        rag = state.get("rag") or {}
        # Open questions and thin evidence get the full tool loop (the agent decides what to look up);
        # an incident that already has graded evidence goes straight to one grounded, guarded call.
        use_loop = (state.get("mode") == "query" or rag.get("abstained") or not rag.get("passages")) \
            and budget_left() >= settings.llm_max_tool_steps + 2
        try:
            return _agent(llm, state, schema, task, facts, locked if agent_locked is None else agent_locked, use_loop)
        except LLMUnavailable:
            pass
    out, by = structure(schema, task, facts, fallback, locked)
    return out, by, None


def _agent(llm, state, schema, task, facts, locked, use_loop=True):
    ctx = ToolContext(state["entity_id"], state["role"])
    rag = state.get("rag") or {}
    seeded = [{"id": p["id"], "title": p["title"], "source": p["source"], "text": p["text"], "origin": p.get("origin", ""), "publisher": p.get("publisher", "")}
              for p in rag.get("passages", [])]
    seed_view = ctx.register(seeded)
    brief = {"task": task, "facts": facts, "evidence_already_retrieved": seed_view,
             "user_message": state.get("message") or "(structured report, no free text)"}
    run = (llm.tool_loop(AGENT_SYSTEM.format(role=ROLE_NAME.get(state["role"], "partner"), steps=settings.llm_max_tool_steps),
                         json.dumps(brief, default=str), build_tools(ctx), "advisor", settings.llm_max_tool_steps)
           if use_loop else AgentRun())
    final_user = (f"Task: {task}\nFACTS: {json.dumps(facts, default=str)}\n"
                  f"EVIDENCE (cite by ref): {json.dumps([{'ref': i + 1, 'title': p['title'][:80], 'text': p['text'][:700]} for i, p in enumerate(ctx.retrieved)])}\n"
                  f"AGENT FINDINGS: {run.text}")
    out = llm.generate_json(schema, FINAL_SYSTEM, final_user, "advisor.final")
    if locked:
        out = out.model_copy(update=locked)

    # ---- guards
    n = len(ctx.retrieved)
    cites = sorted({c for c in getattr(out, "citations", []) if 1 <= c <= n})
    if isinstance(out, AnswerOut) and not out.abstained and not cites:
        # an answer claiming knowledge but citing no retrieved passage is not allowed to stand
        out = out.model_copy(update={"abstained": True, "answer": "I could not find reliable information on this in the knowledge base. "
                                                                  "Please ask an expert or your local sericulture office.", "key_points": [], "citations": []})
    remap = {old: new + 1 for new, old in enumerate(cites)}
    update: dict = {"citations": [remap[c] for c in cites]}
    if isinstance(out, Advisory):
        evidence = [ctx.retrieved[c - 1]["text"] for c in cites] or [p["text"] for p in ctx.retrieved]
        update["ungrounded_steps"] = _grounding(out.mitigation_steps, evidence, json.dumps(facts, default=str))
    out = out.model_copy(update=update)
    cited = [ctx.retrieved[c - 1] for c in cites]
    meta = {"steps": run.steps, "searches": sum(1 for s in run.steps if s["tool"] == "search_knowledge"), "llm_calls": run.calls + 1,
            "rag": {**rag, "passages": [{"id": p["id"], "title": p["title"], "source": p["source"], "topic": p.get("topic", ""), "text": p["text"],
                                         "similarity": 0, "overlap": 0, "relevant": True, "origin": p.get("origin", ""), "publisher": p.get("publisher", "")} for p in cited],
                    "agent_cited": True}}
    return out, ("agent" if use_loop else "gemini"), meta
