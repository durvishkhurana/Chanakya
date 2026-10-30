"""Mission intake: three doors in, one mission card out (docs/IDEA.md 3.2)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from chanakya.core.schemas import (
    Door,
    EventKind,
    Merchant,
    MerchantSignal,
    Mission,
    MissionCard,
    MissionState,
    MissionType,
    SignalKind,
)
from chanakya.missions.ledger import MissionLedger


@dataclass(frozen=True)
class TriggerRule:
    door: Door
    mission_type: MissionType
    goal: str
    why_now: str
    starting_worries: dict[str, float]
    chance: float  # rough chance of success, used for priority
    value: float  # relative value of the outcome
    product: str | None = None
    boost: float = 1.0  # speed-to-lead boost for raised hands


# Starting worries are priors over Concern Bank ids; they must match ids in data/concerns (task A1).
RULES: dict[SignalKind, TriggerRule] = {
    SignalKind.CALLBACK_REQUEST: TriggerRule(
        Door.MERCHANT, MissionType.SALES, "Sell {product} → verified onboarding",
        "Requested a callback on the {product} page",
        {"hidden_charges": 0.5, "competitor_qr": 0.3, "just_busy": 0.2}, 0.6, 1.0, "soundbox", boost=1.5),
    SignalKind.ONBOARDING_STALLED: TriggerRule(
        Door.MERCHANT, MissionType.SALES, "Help finish {product} onboarding",
        "Onboarding started {days} days ago and stopped at {step}",
        {"setup_hassle": 0.45, "data_privacy": 0.3, "trust_in_caller": 0.25}, 0.5, 1.0, "soundbox", boost=1.2),
    SignalKind.PRICE_QUESTION_DROPPED: TriggerRule(
        Door.MERCHANT, MissionType.SALES, "Sell {product} → verified onboarding",
        "Asked the {product} price, then went quiet",
        {"swipe_charges": 0.55, "rental_cost": 0.3, "setup_hassle": 0.15}, 0.4, 1.0, "card_machine", boost=1.2),
    SignalKind.UPI_RISING_NO_SOUNDBOX: TriggerRule(
        Door.DATA, MissionType.SALES, "Sell {product} → verified onboarding",
        "UPI payments up {growth_pct}% this month, no Soundbox",
        {"competitor_qr": 0.5, "hidden_charges": 0.3, "not_needed": 0.2}, 0.35, 0.8, "soundbox"),
    SignalKind.CARD_ATTEMPTS_NO_POS: TriggerRule(
        Door.DATA, MissionType.SALES, "Sell {product} → verified onboarding",
        "{attempts} customers tried to pay by card this week, no card machine",
        {"swipe_charges": 0.55, "rental_cost": 0.3, "setup_hassle": 0.15}, 0.35, 1.0, "card_machine"),
    SignalKind.SOUNDBOX_UNUSED: TriggerRule(
        Door.DATA, MissionType.RETENTION, "Find out why the Soundbox is unused and keep the subscription",
        "Soundbox has not taken a payment for {days} days",
        {"rental_cost": 0.4, "customers_pay_cash": 0.35, "device_reliability": 0.25}, 0.45, 0.7, "soundbox"),
    SignalKind.RENTAL_MISSED: TriggerRule(
        Door.DATA, MissionType.RETENTION, "Understand the missed rental and keep the subscription",
        "Device rental payment missed",
        {"cash_flow": 0.45, "rental_cost": 0.35, "not_needed": 0.2}, 0.4, 0.7, "soundbox"),
    SignalKind.LEAD_LIST_ASSIGNED: TriggerRule(
        Door.HUMAN, MissionType.SALES, "Sell {product} → verified onboarding",
        "From {assigned_by}'s lead list",
        {"hidden_charges": 0.4, "just_busy": 0.3, "trust_in_caller": 0.3}, 0.25, 0.8, "soundbox"),
    SignalKind.FIELD_AGENT_NOTE: TriggerRule(
        Door.HUMAN, MissionType.FOLLOW_UP, "Follow up on the field visit for {product}",
        "Field agent {agent} noted: \"{note}\"",
        {"just_busy": 0.5, "hidden_charges": 0.3, "trust_in_caller": 0.2}, 0.5, 0.9, "soundbox"),
    SignalKind.HUMAN_CALL_DROPPED: TriggerRule(
        Door.HUMAN, MissionType.FOLLOW_UP, "Continue {agent}'s call about {product}",
        "{agent}'s call dropped; continue where it left off",
        {"just_busy": 0.4, "trust_in_caller": 0.3, "hidden_charges": 0.3}, 0.5, 0.9, "soundbox", boost=1.2),
    # Win-back (behind WINBACK_ENABLED): listen for why they left, fix it if a system can; never an offer.
    SignalKind.MERCHANT_CHURNED: TriggerRule(
        Door.DATA, MissionType.WIN_BACK, "Find out why they stopped using {product}, fix it if we can",
        "Stopped using {product} {days} days ago",
        {"device_issue": 0.3, "settlement_delay": 0.2, "rental_cost": 0.2, "not_needed": 0.15,
         "customers_pay_cash": 0.1, "competitor_qr": 0.05}, 0.3, 0.8, "soundbox"),
}

PRODUCT_NAMES = {"soundbox": "Soundbox", "card_machine": "card machine", "qr": "QR", "payment_gateway": "Payment Gateway",
                 "payment_links": "Payment Links", "business_app": "Business app"}

DEFAULT_DETAILS = {"days": "a few", "step": "an unfinished step", "growth_pct": "a lot of", "attempts": "Several",
                   "assigned_by": "a manager", "agent": "a colleague", "note": "follow up"}


class _Details(dict):
    def __missing__(self, key: str) -> str:
        return DEFAULT_DETAILS.get(key, "")


def build_card(signal: MerchantSignal, merchant: Merchant) -> MissionCard:
    """Turn a signal into a mission card: goal, why now, starting worries and priority."""
    rule = RULES[signal.kind]
    if signal.door != rule.door:
        raise ValueError(f"{signal.kind} arrives through the {rule.door} door, not {signal.door}")
    product = signal.details.get("product") or rule.product
    details = _Details(signal.details | {"product": PRODUCT_NAMES.get(product, (product or "").replace("_", " "))})
    worries = signal.details.get("starting_worries") or rule.starting_worries
    return MissionCard(
        merchant_id=merchant.id, merchant_name=merchant.name, language=merchant.language, door=signal.door,
        signal_kind=signal.kind, signal_id=signal.id, mission_type=rule.mission_type,
        goal=rule.goal.format_map(details), product=product, why_now=rule.why_now.format_map(details),
        starting_worries=worries, priority=round(rule.chance * rule.value * rule.boost, 3),
        contact_window=merchant.contact_window,
    )


def _goal_key(card: MissionCard) -> tuple:
    return (card.merchant_id, card.mission_type, card.product)


class MissionIntake:
    """Opens missions from signals. A repeat signal for an open mission with the same goal refreshes it instead."""

    def __init__(self, ledger: MissionLedger, merchants: Callable[[str], Merchant | None]):
        self.ledger = ledger
        self.merchants = merchants

    async def ingest(self, signal: MerchantSignal) -> tuple[Mission, bool]:
        """Return the mission for this signal and whether it was newly created."""
        merchant = self.merchants(signal.merchant_id)
        if merchant is None:
            raise LookupError(f"unknown merchant {signal.merchant_id}")
        card = build_card(signal, merchant)

        missions = self.ledger.store.list()
        if merchant.do_not_call:
            blocked = next((m for m in missions if m.outcome == "do-not-call" and _goal_key(m.card) == _goal_key(card)), None)
            if blocked is not None:
                return blocked, False
        existing = next((m for m in missions if m.is_open and _goal_key(m.card) == _goal_key(card)), None)
        if existing is not None:
            why_now = card.why_now
            if existing.card.why_now not in why_now:
                why_now = f"{card.why_now}; earlier: {existing.card.why_now}"
            refreshed = card.model_copy(update={"priority": max(card.priority, existing.card.priority), "why_now": why_now})
            mission = await self.ledger.update_card(existing.id, refreshed, reason=f"repeat trigger: {signal.kind}")
            await self.ledger.record(mission.id, EventKind.SIGNAL_RECEIVED, signal)
            return mission, False

        mission = await self.ledger.create(card)
        await self.ledger.record(mission.id, EventKind.SIGNAL_RECEIVED, signal)
        if merchant.do_not_call:
            mission = await self.ledger.close(mission.id, MissionState.CLOSED_NOT_INTERESTED, outcome="do-not-call")
        return mission, True
