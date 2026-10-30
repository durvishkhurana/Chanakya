"""Typed tools over the mock systems. Each tool: Pydantic arguments, read or write, and a handler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from chanakya.actions.systems.db import MockDB, now_iso
from chanakya.core.schemas import ToolCall, ToolKind, new_id

Product = Literal["soundbox", "card_machine", "qr", "payment_gateway", "payment_links", "business_app"]
ONBOARDING_URL = "/demo/onboard/{session_id}"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MerchantArgs(Args):
    merchant_id: str


class ProductArgs(MerchantArgs):
    product: Product


class CallbackRequestArgs(ProductArgs):
    note: str = Field("", max_length=300)


class LeadStageArgs(ProductArgs):
    stage: Literal["new", "contacted", "interested", "link_sent", "onboarded", "not_interested"]


class InteractionArgs(MerchantArgs):
    summary: str = Field(min_length=1, max_length=1000)


class OnboardingLinkArgs(ProductArgs):
    channel: Literal["sms", "whatsapp"] = "sms"
    language: str = "hi-IN"


class ReminderArgs(MerchantArgs):
    session_id: str
    channel: Literal["sms", "whatsapp"] = "whatsapp"


class SummaryArgs(MerchantArgs):
    channel: Literal["sms", "whatsapp"] = "whatsapp"
    text: str = Field(min_length=1, max_length=600)


class OnboardingStatusArgs(MerchantArgs):
    session_id: str | None = None


def _iso_datetime(value: str) -> str:
    """A slot or due time must be a real ISO date-time, never free text like "tomorrow"."""
    datetime.fromisoformat(value)  # raises ValueError, which Pydantic reports as invalid arguments
    return value


class FieldVisitArgs(MerchantArgs):
    purpose: Literal["sales", "technician"]
    slot: str = Field(description="ISO date-time of the visit slot")

    @field_validator("slot")
    @classmethod
    def slot_is_iso(cls, value: str) -> str:
        return _iso_datetime(value)


class CallbackArgs(MerchantArgs):
    due_at: str = Field(description="ISO date-time to call back")
    note: str = Field("", max_length=300)

    @field_validator("due_at")
    @classmethod
    def due_at_is_iso(cls, value: str) -> str:
        return _iso_datetime(value)


class TicketArgs(MerchantArgs):
    category: Literal["device", "settlement", "payments", "onboarding", "other"]
    description: str = Field(min_length=1, max_length=1000)


class TicketStatusArgs(MerchantArgs):
    ticket_id: str


@dataclass(frozen=True)
class Tool:
    name: str
    system: str
    kind: ToolKind
    description: str
    args: type[Args]
    handler: Callable[[MockDB, Args, ToolCall], dict]
    irreversible: bool = False


def _merchant(db: MockDB, merchant_id: str) -> dict:
    row = db.one("SELECT * FROM merchants WHERE id = ?", merchant_id)
    if row is None:
        raise LookupError(f"unknown merchant {merchant_id}")
    return row


# ── Intake ───────────────────────────────────────────────────────────────

def create_callback_request(db: MockDB, a: CallbackRequestArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    request_id = new_id("cb")
    db.write("INSERT INTO callback_requests VALUES (?, ?, ?, ?, ?)", request_id, a.merchant_id, a.product, a.note, now_iso())
    return {"callback_request_id": request_id}


# ── CRM ──────────────────────────────────────────────────────────────────

def get_merchant_profile(db: MockDB, a: MerchantArgs, call: ToolCall) -> dict:
    merchant = _merchant(db, a.merchant_id)
    leads = db.all("SELECT product, stage FROM leads WHERE merchant_id = ?", a.merchant_id)
    return {"merchant": merchant, "leads": leads}


def create_lead(db: MockDB, a: ProductArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    existing = db.one("SELECT id FROM leads WHERE merchant_id = ? AND product = ?", a.merchant_id, a.product)
    if existing:
        return {"lead_id": existing["id"], "created": False}
    lead_id = new_id("lead")
    db.write("INSERT INTO leads VALUES (?, ?, ?, 'new', ?, ?)", lead_id, a.merchant_id, a.product, now_iso(), now_iso())
    return {"lead_id": lead_id, "created": True}


def update_lead_stage(db: MockDB, a: LeadStageArgs, call: ToolCall) -> dict:
    lead = create_lead(db, ProductArgs(merchant_id=a.merchant_id, product=a.product), call)
    db.write("UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?", a.stage, now_iso(), lead["lead_id"])
    return {"lead_id": lead["lead_id"], "stage": a.stage}


def log_interaction(db: MockDB, a: InteractionArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    interaction_id = new_id("int")
    db.write("INSERT INTO interactions VALUES (?, ?, ?, ?, ?)", interaction_id, a.merchant_id, call.mission_id, a.summary, now_iso())
    return {"interaction_id": interaction_id}


# ── Messaging and onboarding ─────────────────────────────────────────────

LINK_TEXT = {
    "hi-IN": "Namaste {name}, aapka {product} onboarding link: {link}",
    "pa-IN": "Sat Sri Akal {name}, tuhada {product} onboarding link: {link}",
    "en-IN": "Hello {name}, here is your {product} onboarding link: {link}",
}


def send_onboarding_link(db: MockDB, a: OnboardingLinkArgs, call: ToolCall) -> dict:
    merchant = _merchant(db, a.merchant_id)
    session_id = new_id("onb")
    link = ONBOARDING_URL.format(session_id=session_id)
    db.write("INSERT INTO onboarding_sessions VALUES (?, ?, ?, ?, 'pending', ?, NULL)",
             session_id, a.merchant_id, call.mission_id, a.product, now_iso())
    template = LINK_TEXT.get(a.language, LINK_TEXT["en-IN"])
    body = template.format(name=merchant["name"], product=a.product.replace("_", " "), link=link)
    message_id = new_id("msg")
    db.write("INSERT INTO outbox VALUES (?, ?, ?, ?, ?, ?, 'sent', ?)",
             message_id, a.merchant_id, call.mission_id, a.channel, body, link, now_iso())
    return {"session_id": session_id, "link": link, "message_id": message_id, "body": body}


REMINDER_TEXT = {
    "hi-IN": "Namaste {name}, yaad dila rahe hain: aapka {product} onboarding abhi baaki hai. Link: {link}",
    "pa-IN": "Sat Sri Akal {name}, yaad karwa rahe haan: tuhada {product} onboarding baaki hai. Link: {link}",
    "en-IN": "Hello {name}, a reminder that your {product} onboarding is still open. Link: {link}",
}


def send_onboarding_reminder(db: MockDB, a: ReminderArgs, call: ToolCall) -> dict:
    """The fixed reminder for an open onboarding session; there is no free text to fill in."""
    merchant = _merchant(db, a.merchant_id)
    session = db.one("SELECT * FROM onboarding_sessions WHERE id = ? AND merchant_id = ?", a.session_id, a.merchant_id)
    if session is None:
        raise LookupError(f"unknown onboarding session {a.session_id}")
    if session["status"] == "completed":
        raise LookupError(f"onboarding session {a.session_id} is already completed")
    link = ONBOARDING_URL.format(session_id=a.session_id)
    template = REMINDER_TEXT.get(merchant["language"], REMINDER_TEXT["en-IN"])
    body = template.format(name=merchant["name"], product=session["product"].replace("_", " "), link=link)
    message_id = new_id("msg")
    db.write("INSERT INTO outbox VALUES (?, ?, ?, ?, ?, ?, 'sent', ?)",
             message_id, a.merchant_id, call.mission_id, a.channel, body, link, now_iso())
    return {"message_id": message_id, "body": body, "link": link}


def send_summary(db: MockDB, a: SummaryArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    message_id = new_id("msg")
    db.write("INSERT INTO outbox VALUES (?, ?, ?, ?, ?, NULL, 'sent', ?)",
             message_id, a.merchant_id, call.mission_id, a.channel, a.text, now_iso())
    return {"message_id": message_id}


def get_onboarding_status(db: MockDB, a: OnboardingStatusArgs, call: ToolCall) -> dict:
    if a.session_id:
        row = db.one("SELECT * FROM onboarding_sessions WHERE id = ? AND merchant_id = ?", a.session_id, a.merchant_id)
    else:
        row = db.one("SELECT * FROM onboarding_sessions WHERE merchant_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                     a.merchant_id)
    return {"session": row, "status": row["status"] if row else "none"}


def complete_onboarding(db: MockDB, session_id: str) -> dict:
    """Called by the mock onboarding page, never by the agent: the merchant finishing onboarding."""
    row = db.one("SELECT * FROM onboarding_sessions WHERE id = ?", session_id)
    if row is None:
        raise LookupError(f"unknown onboarding session {session_id}")
    if row["status"] != "completed":
        db.write("UPDATE onboarding_sessions SET status = 'completed', completed_at = ? WHERE id = ?", now_iso(), session_id)
        db.write("UPDATE leads SET stage = 'onboarded', updated_at = ? WHERE merchant_id = ? AND product = ?",
                 now_iso(), row["merchant_id"], row["product"])
        column = {"soundbox": "has_soundbox", "card_machine": "has_card_machine"}.get(row["product"])
        if column:
            db.write(f"UPDATE merchants SET {column} = 1 WHERE id = ?", row["merchant_id"])  # column from a fixed map
    return db.one("SELECT * FROM onboarding_sessions WHERE id = ?", session_id)


# ── Field operations ─────────────────────────────────────────────────────

def book_field_visit(db: MockDB, a: FieldVisitArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    visit_id = new_id("visit")
    db.write("INSERT INTO field_visits VALUES (?, ?, ?, ?, ?, 'booked')", visit_id, a.merchant_id, call.mission_id, a.purpose, a.slot)
    return {"visit_id": visit_id, "slot": a.slot}


def book_callback(db: MockDB, a: CallbackArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    callback_id = new_id("cbk")
    db.write("INSERT INTO callbacks VALUES (?, ?, ?, ?, ?)", callback_id, a.merchant_id, call.mission_id, a.due_at, a.note)
    return {"callback_id": callback_id, "due_at": a.due_at}


# ── Devices ──────────────────────────────────────────────────────────────

def get_device_status(db: MockDB, a: MerchantArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    return {"devices": db.all("SELECT id, kind, status, rental_status FROM devices WHERE merchant_id = ?", a.merchant_id)}


def get_device_usage(db: MockDB, a: MerchantArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    usage = []
    for device in db.all("SELECT id, kind, last_payment_at FROM devices WHERE merchant_id = ?", a.merchant_id):
        last = datetime.fromisoformat(device["last_payment_at"]) if device["last_payment_at"] else None
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)  # older rows were stored without a zone; they are UTC
        idle = (datetime.now(UTC) - last).days if last else None
        usage.append({**device, "days_since_last_payment": idle})
    return {"devices": usage}


def get_device_order_status(db: MockDB, a: MerchantArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    return {"orders": db.all("SELECT id, product, status, created_at FROM device_orders WHERE merchant_id = ?", a.merchant_id)}


# ── Tickets and settlements ──────────────────────────────────────────────

def raise_ticket(db: MockDB, a: TicketArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    ticket_id = new_id("tkt")
    db.write("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, 'open', ?)", ticket_id, a.merchant_id, call.mission_id,
             a.category, a.description, now_iso())
    return {"ticket_id": ticket_id, "status": "open"}


def get_ticket_status(db: MockDB, a: TicketStatusArgs, call: ToolCall) -> dict:
    # Scoped to the merchant, so the gate's same-merchant rule also covers ticket reads.
    row = db.one("SELECT * FROM tickets WHERE id = ? AND merchant_id = ?", a.ticket_id, a.merchant_id)
    if row is None:
        raise LookupError(f"unknown ticket {a.ticket_id}")
    return {"ticket": row}


def resolve_ticket(db: MockDB, ticket_id: str) -> dict:
    """Called by the mock ticketing team, never by the agent: the issue behind a ticket is fixed."""
    if db.one("SELECT id FROM tickets WHERE id = ?", ticket_id) is None:
        raise LookupError(f"unknown ticket {ticket_id}")
    db.write("UPDATE tickets SET status = 'resolved' WHERE id = ?", ticket_id)
    return db.one("SELECT * FROM tickets WHERE id = ?", ticket_id)


def get_settlement_status(db: MockDB, a: MerchantArgs, call: ToolCall) -> dict:
    _merchant(db, a.merchant_id)
    return {"settlements": db.all("SELECT * FROM settlements WHERE merchant_id = ? ORDER BY expected_on DESC", a.merchant_id)}


R, W = ToolKind.READ, ToolKind.WRITE

TOOLS: list[Tool] = [
    Tool("create_callback_request", "intake", W, "Mock intake: record a merchant's callback request.", CallbackRequestArgs, create_callback_request),
    Tool("get_merchant_profile", "crm", R, "Mock CRM: merchant profile and lead stages.", MerchantArgs, get_merchant_profile),
    Tool("create_lead", "crm", W, "Mock CRM: create a lead for a product.", ProductArgs, create_lead),
    Tool("update_lead_stage", "crm", W, "Mock CRM: move a lead to a new stage.", LeadStageArgs, update_lead_stage),
    Tool("log_interaction", "crm", W, "Mock CRM: log a summary of a conversation.", InteractionArgs, log_interaction),
    Tool("send_onboarding_link", "messaging", W, "Mock messaging: send an onboarding link by SMS or WhatsApp.",
         OnboardingLinkArgs, send_onboarding_link, irreversible=True),
    Tool("send_onboarding_reminder", "messaging", W,
         "Mock messaging: send the fixed onboarding reminder for an open onboarding session.", ReminderArgs,
         send_onboarding_reminder, irreversible=True),
    Tool("send_summary", "messaging", W, "Mock messaging: send the merchant a short summary.", SummaryArgs, send_summary,
         irreversible=True),
    Tool("get_onboarding_status", "onboarding", R, "Mock onboarding: status of the merchant's onboarding.",
         OnboardingStatusArgs, get_onboarding_status),
    Tool("book_field_visit", "field_ops", W, "Mock field ops: book a sales or technician visit.", FieldVisitArgs,
         book_field_visit, irreversible=True),
    Tool("book_callback", "field_ops", W, "Mock field ops: schedule a callback.", CallbackArgs, book_callback),
    Tool("get_device_status", "devices", R, "Mock devices: device status and rental status.", MerchantArgs, get_device_status),
    Tool("get_device_usage", "devices", R, "Mock devices: days since each device last took a payment.", MerchantArgs, get_device_usage),
    Tool("get_device_order_status", "devices", R, "Mock devices: device order status.", MerchantArgs, get_device_order_status),
    Tool("raise_ticket", "tickets", W, "Mock ticketing: raise a support ticket.", TicketArgs, raise_ticket, irreversible=True),
    Tool("get_ticket_status", "tickets", R, "Mock ticketing: status of a ticket.", TicketStatusArgs, get_ticket_status),
    Tool("get_settlement_status", "settlements", R, "Mock settlements: recent settlements (read-only).",
         MerchantArgs, get_settlement_status),
]


def default_slot(days: int = 1, hour: int = 11) -> str:
    """An ISO slot ``days`` from now at ``hour`` UTC, for demos and tests."""
    day = datetime.now(UTC) + timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
