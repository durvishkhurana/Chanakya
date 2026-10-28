"""Policy graph: which rules every tool call must pass, by tool kind and system (docs/IDEA.md 3.7).

Each rule returns None when satisfied or a short reason when it blocks.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from chanakya.core.schemas import EventKind, Merchant, Mission, MissionEvent, ToolCall, ToolInfo, ToolKind

SENSITIVE = re.compile(
    r"\b(otp|one[- ]time password|upi ?pin|\bpin\b|cvv|password|passcode|aadhaar|aadhar|pan card|card number)\b",
    re.IGNORECASE,
)
CONTACT_SYSTEMS = {"messaging"}


@dataclass(frozen=True)
class Facts:
    call: ToolCall
    tool: ToolInfo
    mission: Mission
    merchant: Merchant | None
    events: list[MissionEvent]
    local_time: datetime
    calling_hours: tuple[int, int]


Rule = Callable[[Facts], str | None]


def same_merchant(f: Facts) -> str | None:
    """Actions only ever touch the mission's own merchant."""
    target = f.call.args.get("merchant_id")
    if target is not None and target != f.mission.card.merchant_id:
        return "merchant does not match the mission"
    return None


def no_sensitive_data(f: Facts) -> str | None:
    """Never request or send OTP, UPI PIN, CVV, passwords, card numbers or identity documents."""
    for value in f.call.args.values():
        if isinstance(value, str) and (SENSITIVE.search(value) or re.search(r"\b\d{12,19}\b", value)):
            return "arguments mention sensitive data"
    return None


def ai_disclosed(f: Facts) -> str | None:
    """The merchant was told they are talking to an AI before anything changes."""
    if not any(e.kind == EventKind.AI_DISCLOSED for e in f.events):
        return "AI disclosure not recorded"
    return None


def explicit_consent(f: Facts) -> str | None:
    """A write needs a recorded yes for this tool, not withdrawn since."""
    for event in reversed(f.events):
        if event.payload.get("tool") != f.call.tool:
            continue
        if event.kind == EventKind.CONSENT_DECLINED:
            return "merchant declined"
        if event.kind == EventKind.CONSENT_GIVEN:
            return None
    return "no explicit consent for this action"


def not_do_not_call(f: Facts) -> str | None:
    """Respect do-not-call for every contact."""
    if f.merchant is not None and f.merchant.do_not_call:
        return "merchant is on do-not-call"
    return None


def within_calling_hours(f: Facts) -> str | None:
    """Contact only inside calling hours, local time."""
    start, end = f.calling_hours
    if not start <= f.local_time.hour < end:
        return f"outside calling hours ({start}:00-{end}:00 local)"
    return None


def suitable_product(f: Facts) -> str | None:
    """Do not sell a device the merchant already has."""
    product, merchant = f.call.args.get("product"), f.merchant
    if merchant is None or product is None:
        return None
    owned = {"soundbox": merchant.has_soundbox, "card_machine": merchant.has_card_machine}
    if owned.get(product):
        return f"merchant already has a {product.replace('_', ' ')}"
    return None


BASE: list[Rule] = [same_merchant, no_sensitive_data]
WRITE: list[Rule] = [ai_disclosed, explicit_consent]
CONTACT: list[Rule] = [not_do_not_call, within_calling_hours]
SALES_TOOLS = {"send_onboarding_link", "create_lead"}


def rules_for(tool: ToolInfo) -> list[Rule]:
    """The rule path a call must pass, read from the tool's kind and system."""
    rules = list(BASE)
    if tool.kind == ToolKind.WRITE:
        rules += WRITE
    if tool.system in CONTACT_SYSTEMS:
        rules += CONTACT
    if tool.name in SALES_TOOLS:
        rules.append(suitable_product)
    return rules


def evaluate(facts: Facts) -> str | None:
    """First blocking reason, or None when every rule passes."""
    for rule in rules_for(facts.tool):
        reason = rule(facts)
        if reason:
            return reason
    return None
