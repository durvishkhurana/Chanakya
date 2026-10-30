"""Mock WhatsApp and SMS channels (task B13): message templates per language and a simulated inbox.

Templates only fill in a name, a product and a link, never prices, charges or offers. A merchant's reply lands in the
mock inbox and goes back into the mission it answers: it is recorded as a merchant turn, and a clear stop, a request
for a call, "done" or distress each move the mission the same way a spoken reply would.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chanakya.actions.systems.db import MockDB, now_iso
from chanakya.core.schemas import new_id

CHANNELS = ("sms", "whatsapp")
INBOX = """
CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL, mission_id TEXT, channel TEXT NOT NULL, body TEXT NOT NULL,
    intent TEXT NOT NULL, at TEXT NOT NULL
);
"""

# WhatsApp allows line breaks and *bold*; SMS stays one short line with the opt-out word.
TEMPLATES = {
    "link": {
        "whatsapp": {
            "hi-IN": "Namaste {name}\n\nAapka *{product}* onboarding link:\n{link}\n\nRukna ho to STOP likhiye.",
            "pa-IN": "Sat Sri Akal {name}\n\nTuhada *{product}* onboarding link:\n{link}\n\nBand karna hove ta STOP likho.",
            "en-IN": "Hello {name}\n\nHere is your *{product}* onboarding link:\n{link}\n\nReply STOP to opt out.",
        },
        "sms": {
            "hi-IN": "Namaste {name}, aapka {product} onboarding link: {link} Rukne ke liye STOP bhejein.",
            "pa-IN": "Sat Sri Akal {name}, tuhada {product} onboarding link: {link} Band karan layi STOP bhejo.",
            "en-IN": "Hello {name}, your {product} onboarding link: {link} Reply STOP to opt out.",
        },
    },
    "reminder": {
        "whatsapp": {
            "hi-IN": "Namaste {name}, yaad dila rahe hain: aapka *{product}* onboarding abhi baaki hai.\n{link}\n\nRukna ho to STOP likhiye.",
            "pa-IN": "Sat Sri Akal {name}, yaad karwa rahe haan: tuhada *{product}* onboarding baaki hai.\n{link}\n\nBand karna hove ta STOP likho.",
            "en-IN": "Hello {name}, a reminder that your *{product}* onboarding is still open.\n{link}\n\nReply STOP to opt out.",
        },
        "sms": {
            "hi-IN": "Namaste {name}, aapka {product} onboarding baaki hai: {link} Rukne ke liye STOP bhejein.",
            "pa-IN": "Sat Sri Akal {name}, tuhada {product} onboarding baaki hai: {link} Band karan layi STOP bhejo.",
            "en-IN": "Hello {name}, your {product} onboarding is still open: {link} Reply STOP to opt out.",
        },
    },
}

STOP = re.compile(r"^\s*stop\b|\b(unsubscribe|mat bhejo|mat bhejiye|band karo|na bhejo|message mat)\b|मत भेजो|ਨਾ ਭੇਜੋ",
                  re.IGNORECASE)
DONE = re.compile(r"\b(done|completed|ho gaya|ho gya|kar diya|kar dita|ho gea|ho gaya hai)\b|हो गया|कर दिया|ਹੋ ਗਿਆ",
                  re.IGNORECASE)
CALL_ME = re.compile(r"\b(call me|call karo|call kijiye|phone karo|phone kijiye|baat karni|call back)\b|फोन करो|कॉल करो|ਫੋਨ ਕਰੋ",
                     re.IGNORECASE)


def render(kind: str, channel: str, language: str, **fields: str) -> str:
    """The fixed message for ``kind`` (link or reminder) on ``channel``, in the language, English if unknown."""
    by_language = TEMPLATES[kind][channel if channel in CHANNELS else "sms"]
    return by_language.get(language, by_language["en-IN"]).format(**fields)


def classify(body: str) -> str:
    """What a reply asks for: stop, human, done, callback or other. A stop always wins."""
    from chanakya.brain.moves import merchant_declined, merchant_distressed

    if STOP.search(body) or merchant_declined(body):
        return "stop"
    if merchant_distressed(body):
        return "human"
    if CALL_ME.search(body):
        return "callback"
    if DONE.search(body):
        return "done"
    return "other"


def _inbox(db: MockDB) -> None:
    with db.lock, db.conn:
        db.conn.executescript(INBOX)


def thread(db: MockDB, merchant_id: str) -> list[dict]:
    """Messages sent to and received from a merchant, oldest first."""
    _inbox(db)
    sent = [{**row, "direction": "out"} for row in db.all("SELECT * FROM outbox WHERE merchant_id = ?", merchant_id)]
    received = [{**row, "direction": "in"} for row in db.all("SELECT * FROM inbox WHERE merchant_id = ?", merchant_id)]
    return sorted(sent + received, key=lambda m: m["at"])


async def receive_reply(runtime, merchant_id: str, channel: str, body: str) -> dict:
    """A merchant's reply arrives in the mock inbox and goes back into the open mission it answers."""
    from chanakya.core.schemas import EventKind, MissionState, Speaker, Turn

    S = MissionState
    if runtime.db.one("SELECT id FROM merchants WHERE id = ?", merchant_id) is None:
        raise LookupError(f"unknown merchant {merchant_id}")
    _inbox(runtime.db)
    mission = None
    for row in runtime.db.all("SELECT mission_id FROM outbox WHERE merchant_id = ? AND mission_id IS NOT NULL "
                              "ORDER BY at DESC, rowid DESC", merchant_id):
        candidate = runtime.ledger.store.get(row["mission_id"])
        if candidate is not None and candidate.is_open:
            mission = candidate
            break
    intent = classify(body)
    runtime.db.write("INSERT INTO inbox VALUES (?, ?, ?, ?, ?, ?, ?)", new_id("in"), merchant_id,
                     mission.id if mission else None, channel, body, intent, now_iso())
    if mission is None:
        return {"mission_id": None, "intent": intent, "state": None, "outcome": "no open mission; kept in the inbox"}

    ledger = runtime.ledger
    await ledger.attach_turn(mission.id, Turn(speaker=Speaker.MERCHANT, text=body, language=mission.card.language,
                                              at=runtime.clock()))
    outcome = "recorded for a person to read"
    if intent == "stop":
        # A decline naming the messaging tools blocks every further message; the verifier then stops nudging.
        await ledger.record(mission.id, EventKind.CONSENT_DECLINED, {
            "utterance": body, "channel": channel,
            "tools": ["send_onboarding_link", "send_onboarding_reminder", "send_summary"]})
        outcome = "no more messages; one last passive check, then the mission closes"
    elif intent == "human":
        await runtime.handoffs.escalate(mission.id, f"{channel} reply asks for a person: {body[:120]}",
                                        urgent=True)
        outcome = "handed to a person"
    elif intent == "callback" and S.SCHEDULED in _next_states(mission.state):
        runtime.scheduler.cancel_all(mission.id)  # the call replaces pending reminders and checks
        await ledger.advance(mission.id, S.SCHEDULED, reason=f"merchant asked for a call on {channel}")
        await ledger.record(mission.id, EventKind.FOLLOWUP_SCHEDULED,
                            {"kind": "callback", "due_at": runtime.clock().isoformat(), "channel": channel})
        outcome = "callback due now"
    elif intent == "done":
        sessions = {job.payload.get("session_id") for job in runtime.scheduler.pending(mission.id) if job.kind == "verify"}
        for session_id in sessions - {None}:
            await runtime.verifier.check_now(session_id)  # the system decides, never the merchant's word
        outcome = "checked the onboarding system" if sessions else "noted; nothing to check yet"
    else:
        await ledger.record(mission.id, EventKind.NOTE, {"text": f"{channel} reply needs a person to read: {body[:200]}"})
    return {"mission_id": mission.id, "intent": intent, "state": ledger.store.get(mission.id).state.value,
            "outcome": outcome}


def _next_states(state):
    from chanakya.missions.state import ALLOWED

    return ALLOWED[state]


router = APIRouter(prefix="/api/messages", tags=["messages"])


class Reply(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=80)
    channel: str = Field(default="whatsapp", pattern="^(sms|whatsapp)$")
    body: str = Field(min_length=1, max_length=1000)


@router.get("/{merchant_id}")
async def get_thread(merchant_id: str) -> list[dict]:
    """The mock WhatsApp and SMS thread with one merchant."""
    from chanakya.missions.runtime import get_runtime

    return thread(get_runtime().db, merchant_id)


@router.post("/reply")
async def post_reply(reply: Reply) -> dict:
    """Simulate a merchant replying on WhatsApp or SMS; the reply goes back into their open mission."""
    from chanakya.missions.runtime import get_runtime

    try:
        return await receive_reply(get_runtime(), reply.merchant_id, reply.channel, reply.body)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
