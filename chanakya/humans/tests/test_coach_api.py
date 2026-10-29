"""Coach mode API on the recorded (fictional) human telecaller call."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chanakya.humans.coach_api import router


def make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def play_recorded(http: TestClient) -> tuple[dict, list[dict]]:
    """Start a session and post every turn of the recorded call; return the session and each response."""
    recorded = http.get("/api/coach/recorded").json()
    session = http.post("/api/coach/sessions", json={"recorded": True}).json()
    replies = [http.post(f"/api/coach/sessions/{session['session_id']}/turns", json=turn).json()
               for turn in recorded["turns"]]
    return session, replies


def test_recorded_call_is_labelled_fictional_and_has_both_speakers():
    recorded = make_client().get("/api/coach/recorded").json()
    assert "fictional" in recorded["metadata"]["description"]
    assert {t["speaker"] for t in recorded["turns"]} == {"human_agent", "merchant"}


def test_one_suggestion_per_merchant_turn_and_none_for_the_telecaller():
    http = make_client()
    session, replies = play_recorded(http)
    recorded = http.get("/api/coach/recorded").json()
    for turn, reply in zip(recorded["turns"], replies, strict=True):
        assert (reply["suggestion"] is not None) == (turn["speaker"] == "merchant")
    assert replies[-1]["suggestions"] == sum(t["speaker"] == "merchant" for t in recorded["turns"])
    assert session["starting_worries"] and abs(sum(session["starting_worries"].values()) - 1) < 1e-6


def test_suggestions_follow_the_call_with_sourced_answers():
    _, replies = play_recorded(make_client())
    suggestions = [r["suggestion"] for r in replies if r["suggestion"]]
    first_qr = next(s for s in suggestions if s["move"]["concern"] == "competitor_qr")
    assert first_qr["move"]["type"] == "RESOLVE_CONCERN" and first_qr["guide"]["how"]
    assert all(src["url"].startswith("https://") and src["reviewed"] for s in suggestions if s["guide"]
               for src in s["guide"]["sources"])
    assert suggestions[-1]["move"]["type"] == "CONFIRM_CONSENT", "an unprompted yes still needs a clear consent question"
    assert replies[3]["worries"]["competitor_qr"] > replies[0]["worries"]["competitor_qr"]
    assert all(r["handoff"] is None for r in replies), "the recorded call never needs a senior"


def test_recorded_replays_are_identical():
    http = make_client()
    runs = [[r["suggestion"]["key"] for r in play_recorded(http)[1] if r["suggestion"]] for _ in range(2)]
    assert runs[0] == runs[1] == ["RESOLVE_CONCERN(competitor_qr)", "RESOLVE_CONCERN(competitor_qr)",
                                  "RESOLVE_CONCERN(hidden_charges)", "RESOLVE_CONCERN(rental_cost)",
                                  "CONFIRM_CONSENT(send_onboarding_link)"]


def test_distress_drafts_a_handoff_card_once():
    http = make_client()
    sid = http.post("/api/coach/sessions", json={"merchant_name": "Gupta Medicals (mock)"}).json()["session_id"]
    text = "Mera settlement teen din se atka hai, main bahut pareshaan hoon, complaint karunga!"
    reply = http.post(f"/api/coach/sessions/{sid}/turns", json={"speaker": "merchant", "text": text}).json()
    assert reply["suggestion"]["move"]["type"] == "ESCALATE"
    card = reply["handoff"]
    assert card["merchant_said"] == text and "Gupta Medicals (mock)" in card["summary"] and card["open_concerns"]
    again = http.post(f"/api/coach/sessions/{sid}/turns", json={"speaker": "merchant", "text": "Jaldi karo"}).json()
    assert again["handoff"] == card


def test_unknown_session_and_move_are_rejected():
    http = make_client()
    assert http.post("/api/coach/sessions/nope/turns", json={"speaker": "merchant", "text": "hi"}).status_code == 404
    sid = http.post("/api/coach/sessions", json={}).json()["session_id"]
    bad = http.post(f"/api/coach/sessions/{sid}/turns", json={"speaker": "human_agent", "text": "hi", "move": "GIVE_DISCOUNT"})
    assert bad.status_code == 422
    assert http.post(f"/api/coach/sessions/{sid}/turns", json={"speaker": "agent", "text": "hi"}).status_code == 422
