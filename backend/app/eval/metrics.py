"""Metric computations for Table 5. Pure functions over recorded run data."""
import re
from collections import Counter

from pydantic import ValidationError

from app.llm.schemas import Advisory, AnswerOut, FindingOut, JudgeOut, RiskOut
from app.llm.structured import groq_enabled, structure
from app.rag.agentic import keywords, overlap, retrieve

PCT = lambda n, d: round(100.0 * n / d, 1) if d else None  # noqa: E731


def is_subsequence(needle: tuple, hay: list[str]) -> bool:
    it = iter(hay)
    return all(x in it for x in needle)


def used_tools(trace: list[dict]) -> list[str]:
    return [t for step in trace for t in step.get("tools", [])]


def validate(model, data) -> bool:
    try:
        model.model_validate(data)
        return True
    except ValidationError:
        return False


def output_validity(payload: dict) -> tuple[int, int]:
    """(valid, checked) over the structured outputs of one incident."""
    checks = []
    if payload.get("finding") and "label" in payload["finding"]:
        checks.append(validate(FindingOut, payload["finding"]))
    if payload.get("risk"):
        checks.append(validate(RiskOut, payload["risk"]))
    adv = payload.get("advisory")
    if adv:
        checks.append(validate(Advisory if adv.get("type") == "advisory" else AnswerOut,
                               {k: v for k, v in adv.items() if k not in ("type", "structured_by")}))
    return sum(checks), len(checks)


# ---------------------------------------------------------------- B/C/D: answer, grounding, uncertainty
def answer_text(adv: dict) -> str:
    if not adv:
        return ""
    return " ".join([adv.get("answer", "")] + adv.get("key_points", []) + adv.get("mitigation_steps", []))


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if len(s.strip()) > 20]


def supported(claim: str, passages: list[str], thr: float = 0.6) -> bool:
    """A claim is supported if most of its content words appear in one retrieved passage and any
    number it states appears in the evidence."""
    nums = set(re.findall(r"\d+(?:\.\d+)?", claim))
    for p in passages:
        if overlap(claim, p) >= thr and all(n in p for n in nums):
            return True
    return False


def correctness(text: str, must: list[list[str]]) -> bool:
    low = text.lower()
    return all(any(k in low for k in group) for group in must)


def judge(question: str, text: str, checklist: list[str]) -> tuple[float, float, str]:
    """Completeness (checklist coverage) and relevance. LLM judge when Groq is configured,
    heuristic otherwise (reported in the output so the two are never confused)."""
    low = text.lower()

    def fb():
        comp = sum(1 for k in checklist if k in low) / max(len(checklist), 1)
        rel = min(1.0, overlap(question, text) * 1.5) if text else 0.0
        return JudgeOut(completeness=round(comp, 2), relevance=round(rel, 2))
    out, by = structure(JudgeOut, "Score 0-1: completeness against the checklist elements, and relevance of the answer to the question.",
                        {"question": question, "answer": text, "checklist": checklist}, fb)
    return out.completeness, out.relevance, "groq" if by.startswith("groq") else "heuristic"


def retrieval_scores(question: str, relevant_sources: list[str], k: int = 5) -> tuple[float, float]:
    """Document-level Recall@K and Context-Precision@K for the top-K retrieved chunks."""
    got = retrieve(question, k)
    got_sources = [p.source for p in got]
    rel = set(relevant_sources)
    recall = len(rel & set(got_sources)) / len(rel) if rel else 0.0
    precision = sum(1 for s in got_sources if s in rel) / len(got_sources) if got_sources else 0.0
    return recall, precision


def summarise(counter: Counter, name: str, num: str, den: str):
    return PCT(counter[num], counter[den])
