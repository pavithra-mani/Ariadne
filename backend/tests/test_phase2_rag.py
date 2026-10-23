from app.rag.agentic import agentic_rag, grade, keywords, retrieve
from app.rag.ingest import chunk


def test_chunker_keeps_headings_and_skips_banner():
    cs = chunk("# A\n> PLACEHOLDER banner\nBody one.\n\n## B\nBody two.")
    assert cs == ["A: Body one.", "B: Body two."]


def test_grounded_answer_with_citations():
    r = agentic_rag("my silkworms have milky fluid and climb the tray edge")
    assert not r.abstained and r.points
    assert "grasserie" in " ".join(p.text.lower() for p in r.passages)
    assert all(1 <= pt["citation"] <= len(r.passages) for pt in r.points)


def test_topic_filter_is_respected():
    r = agentic_rag("white powder on leaves", topics=["mulberry"])
    assert not r.abstained and r.passages[0].topic == "mulberry"


def test_abstains_on_out_of_scope():
    for q in ("what is the capital of France", "how to cook biryani"):
        r = agentic_rag(q)
        assert r.abstained and not r.points and r.reason


def test_rewrite_recovers_weak_query():
    r = agentic_rag("yarn stock low")
    assert not r.abstained


def test_api_ask_requires_auth_and_answers(client, auth):
    assert client.post("/api/knowledge/ask", json={"question": "how to store cocoons"}).status_code == 401
    r = client.post("/api/knowledge/ask", headers=auth("sf1"), json={"question": "how to store fresh cocoons"})
    assert r.status_code == 200 and r.json()["points"]
    assert client.get("/api/knowledge/stats", headers=auth("sf1")).json()["chunks"] > 0
