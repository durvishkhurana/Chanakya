"""Simulated signal feed for the demo merchants seeded in the mock systems. Fictional data only."""

from __future__ import annotations

from chanakya.core.schemas import Door, MerchantSignal, SignalKind


def demo_feed() -> list[MerchantSignal]:
    """Signals through all three doors, matching ``chanakya.actions.systems.seed``.

    Ramesh is left out on purpose: in the demo his mission starts live from the callback button.
    """
    return [
        MerchantSignal(merchant_id="mer_imran", kind=SignalKind.ONBOARDING_STALLED, door=Door.MERCHANT,
                       source="onboarding funnel", details={"days": 2, "step": "bank details", "product": "soundbox"}),
        MerchantSignal(merchant_id="mer_gurpreet", kind=SignalKind.SOUNDBOX_UNUSED, door=Door.DATA,
                       source="device telemetry", details={"days": 8}),
        MerchantSignal(merchant_id="mer_anita", kind=SignalKind.CARD_ATTEMPTS_NO_POS, door=Door.DATA,
                       source="payment attempts", details={"attempts": 12}),
        MerchantSignal(merchant_id="mer_lakshmi", kind=SignalKind.RENTAL_MISSED, door=Door.DATA,
                       source="billing"),
        MerchantSignal(merchant_id="mer_sharma", kind=SignalKind.UPI_RISING_NO_SOUNDBOX, door=Door.DATA,
                       source="transaction trends", details={"growth_pct": 64}),
        MerchantSignal(merchant_id="mer_sharma", kind=SignalKind.LEAD_LIST_ASSIGNED, door=Door.HUMAN,
                       source="Sunita (regional sales head)", details={"assigned_by": "Sunita"}),
        MerchantSignal(merchant_id="mer_baldev", kind=SignalKind.LEAD_LIST_ASSIGNED, door=Door.HUMAN,
                       source="Sunita (regional sales head)", details={"assigned_by": "Sunita"}),
    ]
