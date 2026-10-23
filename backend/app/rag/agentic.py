"""Agentic RAG: retrieve -> grade -> (rewrite -> retrieve)* -> cite or abstain.

The answer is extractive (sentences lifted from graded chunks), so every claim is grounded and
citable by construction. An LLM may later restructure it (see app.llm.structured) but may not
add facts.
"""
import re
from dataclasses import dataclass, field

import math
from functools import lru_cache

from app.rag.store import collection

STOP = set("""a an the and or of to in on for with is are was were be been it this that these those
my our your his her their at by from as how what why when which who whom do does did can could should
would i we you they have has had not no any some very more most about into than then there here if
get got please tell me manage deal need many much best good look looks""".split())

# Domain expansion used when the first retrieval is weak (rule-based query rewrite)
EXPANSIONS = {
    "yellow": "yellowing leaves", "spots": "leaf spot", "white": "white powder",
    "dying": "disease symptoms", "sick": "disease symptoms", "worms": "silkworm larvae",
    "worm": "silkworm larvae", "milky": "grasserie", "vomit": "flacherie", "chalky": "muscardine",
    "stock": "stock storage planning", "delay": "delivery delay", "demand": "demand surge",
    "yarn": "raw silk yarn", "low": "shortfall",
}
MIN_SIM, MIN_OVERLAP, STRONG_SIM = 0.28, 0.45, 0.58
MAX_REWRITES = 2


def keywords(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2]


def stem(w: str) -> str:
    """Crude stemmer so silkworm/silkworms, store/stored/storage and leaf/leaves compare equal."""
    if w in ("leaves", "leaf"):
        return "leaf"
    return w[:4] if len(w) > 4 else w


@lru_cache(maxsize=4)
def _idf(n_chunks: int) -> dict[str, float]:
    """Inverse document frequency over the knowledge base (keyed by size so re-ingest refreshes it)."""
    docs = collection("knowledge").get()["documents"]
    df: dict[str, int] = {}
    for d in docs:
        for w in {stem(x) for x in keywords(d)}:
            df[w] = df.get(w, 0) + 1
    n = max(len(docs), 1)
    return {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}


def _weight(w: str) -> float:
    idf = _idf(collection("knowledge").count())
    # a query term the KB has never seen is maximally informative: its absence must hurt relevance
    return idf.get(w, math.log(len(idf) + 2) + 1 if idf else 1.0)


def overlap(query: str, passage: str) -> float:
    """IDF-weighted share of the query's content stems found in the passage."""
    q = {stem(w) for w in keywords(query)}
    if not q:
        return 0.0
    p = {stem(w) for w in keywords(passage)}
    total = sum(_weight(w) for w in q)
    return sum(_weight(w) for w in q & p) / total if total else 0.0


@dataclass
class Passage:
    id: str
    title: str
    source: str
    topic: str
    text: str
    similarity: float
    overlap: float
    relevant: bool = False

    def dict(self) -> dict:
        return {"id": self.id, "title": self.title, "source": self.source, "topic": self.topic,
                "text": self.text, "similarity": round(self.similarity, 3),
                "overlap": round(self.overlap, 3), "relevant": self.relevant}


@dataclass
class RagResult:
    query: str
    queries_tried: list[str] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)  # relevant ones, best first
    points: list[dict] = field(default_factory=list)       # [{text, citation}]
    abstained: bool = False
    confidence: float = 0.0
    reason: str = ""

    def dict(self) -> dict:
        return {"query": self.query, "queries_tried": self.queries_tried,
                "passages": [p.dict() for p in self.passages], "points": self.points,
                "abstained": self.abstained, "confidence": round(self.confidence, 3),
                "reason": self.reason}


def retrieve(query: str, k: int = 5, topics: list[str] | None = None) -> list[Passage]:
    col = collection("knowledge")
    if col.count() == 0:
        return []
    where = None
    if topics:
        where = {"topic": topics[0]} if len(topics) == 1 else {"topic": {"$in": topics}}
    res = col.query(query_texts=[query], n_results=k, where=where)
    out = []
    for i, doc in enumerate(res["documents"][0]):
        m = res["metadatas"][0][i]
        out.append(Passage(res["ids"][0][i], m["title"], m["source"], m["topic"], doc,
                           1.0 - res["distances"][0][i], overlap(query, doc)))
    return out


def grade(query: str, passages: list[Passage]) -> list[Passage]:
    """Relevance grading: semantic similarity AND lexical grounding in the query terms."""
    for p in passages:
        p.overlap = overlap(query, p.text)
        p.relevant = p.similarity >= MIN_SIM and (p.overlap >= MIN_OVERLAP or p.similarity >= STRONG_SIM)
    good = [p for p in passages if p.relevant]
    return sorted(good, key=lambda p: -(0.5 * p.similarity + 0.5 * p.overlap))  # hybrid dense + lexical rank


def rewrite(query: str, attempt: int, hint: str = "") -> str:
    words = keywords(query)
    extra = [EXPANSIONS[w] for w in words if w in EXPANSIONS]
    if attempt == 1:
        return " ".join(dict.fromkeys(words + extra))  # keyword form + domain synonyms
    return " ".join(dict.fromkeys(["sericulture", hint] + words + extra)).strip()


def _sentences(text: str) -> list[str]:
    body = text.split(": ", 1)[1] if ": " in text[:80] else text
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.replace("\n", " ")) if len(s.strip()) > 25]


# What kind of sentence the user is asking for -> which labelled sentences ("Mitigation: ...") to favour
INTENTS = [(re.compile(r"manag|treat|control|cure|prevent|mitigat|what (should|to) do|handle|remed|overcome", re.I), "mitigation"),
           (re.compile(r"symptom|look|identif|sign|recogni", re.I), "symptoms"),
           (re.compile(r"cause|why|transmit|spread|reason", re.I), "cause")]


def _intent_bonus(query: str, sentence: str) -> float:
    return 0.5 if any(rx.search(query) and sentence.lower().startswith(label) for rx, label in INTENTS) else 0.0


def _heading(text: str) -> str:
    return text.split(": ", 1)[0] if ": " in text[:80] else ""


def extract_points(query: str, passages: list[Passage], limit: int = 5, intent: str = "") -> list[dict]:
    """Pick the most query-relevant sentences. Passages are visited in rank order and each
    contributes its best sentence first (diversity), then remaining slots go to the best scores.
    A passage's heading counts towards relevance ('Storage conditions' for a storage question)."""
    per_passage = []
    for n, p in enumerate(passages, 1):
        head = overlap(query, _heading(p.text))
        all_s = _sentences(p.text)
        sents = sorted(((overlap(query, s) + _intent_bonus(query + " " + intent, s) + 0.6 * head + 0.2 * p.similarity + 0.1 * (1 - i / max(len(all_s), 1)), s)
                        for i, s in enumerate(all_s)), reverse=True)
        per_passage.append([(sc, s, n) for sc, s in sents])
    out, seen = [], set()
    for ranked in per_passage:                       # round 1: best sentence of each passage
        for sc, s, n in ranked[:1]:
            if s not in seen and len(out) < limit:
                seen.add(s)
                out.append({"text": s, "citation": n, "_score": sc})
    rest = sorted((t for ranked in per_passage for t in ranked[1:]), reverse=True)
    for sc, s, n in rest:                            # round 2: highest remaining scores
        if s not in seen and len(out) < limit:
            seen.add(s)
            out.append({"text": s, "citation": n, "_score": sc})
    for o in out:
        o.pop("_score")
    return out


def agentic_rag(query: str, topics: list[str] | None = None, hint: str = "", k: int = 8, intent: str = "") -> RagResult:
    res = RagResult(query=query)
    q = query
    for attempt in range(MAX_REWRITES + 1):
        if attempt:
            q = rewrite(query, attempt, hint)
            if q in res.queries_tried:
                continue
        res.queries_tried.append(q)
        good = grade(q, retrieve(q, k, topics))
        if not good and topics:  # widen scope once before giving up on this attempt
            good = grade(q, retrieve(q, k, None))
        if good:
            res.passages = good[:3]
            res.points = extract_points(q, res.passages, intent=intent)
            res.confidence = max(p.similarity for p in good)
            return res
    res.abstained = True
    res.reason = "No passage in the knowledge base was relevant enough to answer reliably."
    return res
