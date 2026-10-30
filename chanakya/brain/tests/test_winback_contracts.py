"""Win-back and permission-first contracts line up across core, the brain and the Concern Bank (task W0)."""

from datetime import UTC, datetime

import pytest

from chanakya.brain.concern_bank import (
    default_bank,
    knowledge_node_ids,
    load_concerns,
    load_personas,
    load_priors,
    validate,
)
from chanakya.brain.contracts import schemas as brain
from chanakya.brain.core_adapters import TRIGGERS, to_brain_card, to_brain_merchant, to_core_merchant, to_core_move
from chanakya.core import schemas as core

CHURNED = datetime(2026, 9, 20, tzinfo=UTC)


def test_every_core_signal_maps_to_a_brain_trigger():
    assert set(TRIGGERS) == set(core.SignalKind)
    assert TRIGGERS[core.SignalKind.MERCHANT_CHURNED] == brain.TriggerType.MERCHANT_CHURNED
    assert brain.TRIGGER_DOORS[brain.TriggerType.MERCHANT_CHURNED] == brain.Door.DATA


def test_mission_kinds_and_moves_mirror_by_value():
    assert {k.value for k in core.MissionType} == {k.value for k in brain.MissionKind}
    assert {m.value for m in core.MoveType} == {m.value for m in brain.MoveType}
    assert to_core_move(brain.Move(type=brain.MoveType.ASK_PERMISSION), "m").type == core.MoveType.ASK_PERMISSION


@pytest.mark.parametrize("relationship,churned_at", [("former", CHURNED), ("customer", None), ("prospect", None)])
def test_both_merchant_models_round_trip_through_the_adapters(relationship, churned_at):
    merchant = core.Merchant(id="mer_old", name="Old Kirana (mock)", business_type="kirana", city="Patna",
                             contact_window={"start_hour": 10, "end_hour": 18}, has_soundbox=True,
                             relationship=relationship, churned_at=churned_at)
    mirrored = to_brain_merchant(merchant)
    assert (mirrored.relationship, mirrored.churned_at, mirrored.devices) == (relationship, churned_at, ["soundbox"])
    back = to_core_merchant(mirrored)
    assert back.model_dump(exclude={"phone_last4"}) == merchant.model_dump(exclude={"phone_last4"})
    assert to_brain_merchant(back) == mirrored


def test_the_bank_validates_with_a_win_back_prior_over_existing_concerns():
    concerns, priors = load_concerns(), load_priors()
    assert validate(concerns, priors, load_personas(), knowledge_node_ids()) == []
    prior = priors[brain.TriggerType.MERCHANT_CHURNED]
    assert abs(sum(prior.values()) - 1) < 1e-9
    assert set(prior) <= {"device_issue", "rental_cost", "settlement_delay", "customers_pay_cash", "not_needed",
                          "competitor_qr"}
    assert default_bank().prior_for(brain.TriggerType.MERCHANT_CHURNED)


def test_a_win_back_card_becomes_a_brain_card_for_a_former_customer():
    card = core.MissionCard(merchant_id="mer_old", merchant_name="Old Kirana (mock)", door=core.Door.DATA,
                            signal_kind=core.SignalKind.MERCHANT_CHURNED, signal_id="sig", why_now="Stopped",
                            mission_type=core.MissionType.WIN_BACK, goal="Find out why", product="soundbox",
                            starting_worries={"device_issue": 0.6, "not_needed": 0.4})
    mirrored = to_brain_card(core.Mission(id="m_wb", card=card))
    assert mirrored.kind == brain.MissionKind.WIN_BACK and mirrored.trigger == brain.TriggerType.MERCHANT_CHURNED
    assert mirrored.merchant.relationship == "former"
