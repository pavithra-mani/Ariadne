from pathlib import Path

IMG = Path(__file__).resolve().parents[2] / "data" / "images"


def chat(client, headers, message="", img=None, fields=None):
    import json
    files = {"image": (img, open(IMG / img, "rb"), "image/jpeg")} if img else None
    r = client.post("/api/chat", headers=headers, data={"message": message, "fields": json.dumps(fields or {})}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def test_silkworm_photo_full_pipeline(client, auth):
    inc = chat(client, auth("sf1"), "my worms look sick", "grasserie_sample.jpg", {"affected_pct": 50})
    p = inc["payload"]
    assert p["finding"]["label"] == "grasserie" and p["finding"]["is_stub"]
    assert inc["severity"] == "critical" and inc["priority"] == "P1"
    assert p["rag"]["points"] and not p["rag"]["abstained"]
    assert p["advisory"]["type"] == "advisory" and p["advisory"]["mitigation_steps"]
    assert p["advisory"]["escalate"] is True
    assert p["supply_impact"]["n_affected"] >= 1
    nodes = [t["node"] for t in inc["trace"]]
    assert nodes[:3] == ["intake", "triage_supervisor", "silkworm_agent"] and "finalize" == nodes[-1]
    assert inc["status"] == "advised" and inc["solution"]


def test_mulberry_mild_case_does_not_escalate(client, auth):
    inc = chat(client, auth("mf1"), "leaf problem", "powdery_mildew_sample.jpg", {"affected_pct": 8})
    assert inc["payload"]["finding"]["label"] == "powdery_mildew"
    assert inc["payload"]["advisory"]["escalate"] is False
    assert inc["priority"] in ("P4", "P3")


def test_healthy_leaf_is_not_an_incident(client, auth):
    inc = chat(client, auth("mf1"), "check this", "healthy_leaf.jpg")
    assert inc["is_issue"] is False and inc["priority"] is None


def test_low_confidence_abstains(client, auth):
    inc = chat(client, auth("sf1"), "", "mystery_photo.jpg")
    f = inc["payload"]["finding"]
    if f["uncertain"]:
        assert inc["payload"]["advisory"]["headline"].startswith("Diagnosis uncertain")
        assert inc["payload"]["supply_impact"]["at_risk"] is False


def test_text_only_symptoms_and_questions(client, auth):
    inc = chat(client, auth("sf1"), "larvae are restless, climb tray edge, milky fluid, swollen shiny")
    assert inc["payload"]["finding"]["label"] == "grasserie"
    q = chat(client, auth("sf1"), "how should fresh cocoons be stored?")
    assert q["is_issue"] is False and q["payload"]["advisory"]["type"] == "answer"
    ood = chat(client, auth("sf1"), "what is the capital of France?")
    assert ood["payload"]["advisory"]["abstained"] is True


def test_recurrence_recalls_memory(client, auth):
    chat(client, auth("mf2"), "x", "leaf_blight_sample.jpg", {"affected_pct": 30})
    again = chat(client, auth("mf2"), "x", "leaf_blight_sample.jpg", {"affected_pct": 30})
    assert again["payload"]["memory"]["recurring"] is True


def test_incident_visibility_and_validation(client, auth):
    inc = chat(client, auth("mf1"), "x", "leaf_blight_sample.jpg")
    assert client.get(f"/api/incidents/{inc['id']}", headers=auth("mf1")).status_code == 200
    assert client.get(f"/api/incidents/{inc['id']}", headers=auth("mf3")).status_code == 404
    assert client.post("/api/chat", headers=auth("mf1"), data={"message": ""}).status_code == 400
    bad = client.post("/api/chat", headers=auth("mf1"), data={"message": "hi"}, files={"image": ("a.exe", b"x", "application/octet-stream")})
    assert bad.status_code == 400


# ---- silkworm image model says "diseased, type unknown" (label silkworm_disease_unspecified)
def test_generic_silkworm_disease_asks_questions_and_requires_expert(client, auth):
    inc = chat(client, auth("sf3"), "my worms look unwell", "silkworm_disease_unspecified_sample.jpg", {"affected_pct": 30})
    f, adv = inc["payload"]["finding"], inc["payload"]["advisory"]
    assert f["label"] == "silkworm_disease_unspecified" and f["provisional"] is True and not f["uncertain"]
    assert f["infectious"] and "milky fluid" in f["follow_up_question"] and "pepper" in f["follow_up_question"]
    assert adv["escalate"] is True and "expert" in adv["headline"].lower()
    assert any("milky fluid" in q for q in adv["follow_up"])
    steps = " ".join(adv["mitigation_steps"]).lower()
    assert "expert" in steps or "extension officer" in steps
    assert inc["payload"]["rag"]["points"], "generic hygiene steps must come from the knowledge base"
    assert inc["priority"] in ("P1", "P2", "P3") and inc["severity"] in ("moderate", "high", "critical")


def test_symptom_text_names_the_disease_when_image_is_generic(client, auth):
    inc = chat(client, auth("sf4"), "larvae restless, climbing the tray edge, milky fluid, swollen shiny skin",
               "silkworm_disease_unspecified_sample.jpg", {"affected_pct": 30})
    f = inc["payload"]["finding"]
    assert f["label"] == "grasserie" and f["source"] == "image+symptoms" and not f.get("provisional")
    assert f["image_label"] == "silkworm_disease_unspecified"


def test_llm_cannot_drop_the_question_or_expert_confirmation_for_a_generic_disease(client, auth):
    """Even if the model writes an advisory with escalate=False and no follow-up, the generic-disease guard restores both."""
    from app.llm.provider import set_llm_override
    from app.llm.schemas import Advisory
    from tests.fakes import FakeLLM
    set_llm_override(FakeLLM(json={"advisor.final": lambda s, u: Advisory(headline="Probably fine", diagnosis="Looks like a minor issue.",
                                                                           mitigation_steps=["Keep feeding."], escalate=False)}))
    inc = chat(client, auth("sf5"), "worms look unwell", "silkworm_disease_unspecified_sample.jpg", {"affected_pct": 30})
    adv = inc["payload"]["advisory"]
    assert adv["escalate"] is True and any("milky fluid" in q for q in adv["follow_up"])
    assert any("expert" in s.lower() or "extension officer" in s.lower() for s in adv["mitigation_steps"])
