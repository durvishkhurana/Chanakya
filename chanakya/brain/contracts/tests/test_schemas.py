import pytest
from pydantic import ValidationError

from chanakya.brain.contracts import schemas as s
from chanakya.brain.contracts.fakes import sample_card, sample_state


def round_trip(model):
    restored = type(model).model_validate_json(model.model_dump_json())
    assert restored == model
    return restored


def test_every_contract_round_trips_to_json():
    card = sample_card()
    move = s.Move(type=s.MoveType.RESOLVE_CONCERN, concern="hidden_charges", reason="top concern")
    call = s.ToolCall(tool="send_onboarding_link", args={"merchant_id": "mer_test"}, mission_id=card.mission_id)
    result = s.ToolResult(call_id=call.call_id, ok=True, data={"mock": True})
    decision = s.ActionDecision(call=call, verdict="executed", reason="ok", result=result)
    turn = s.Turn(speaker="merchant", text="Charges kitne hain?", language="hi-IN", pause_before_ms=900)
    transcript = s.Transcript(mission_id=card.mission_id, turns=[turn],
                              consents=[s.ConsentRecord(tool="send_onboarding_link", turn_index=0, utterance="Haan bhejo")])
    models = [
        card,
        s.Mission(card=card),
        s.MerchantSignal(merchant_id="mer_test", trigger=s.TriggerType.UPI_RISING_NO_SOUNDBOX, data={"growth": 0.4}),
        s.MissionEvent(mission_id=card.mission_id, kind="Test", payload={"a": 1}),
        s.Persona(persona_id="p1", business_type="kirana", city="Jaipur", language="hi-IN", patience=0.5,
                  busyness=0.4, tech_comfort=0.3, hidden_concerns=["hidden_charges"], willingness_prior=0.4),
        s.Concern(concern_id="hidden_charges", description="Worried about charges",
                  phrasings={"hindi": ["Koi hidden charge?"]},
                  resolve_conditions=[s.ResolveCondition(description="Point to official pricing",
                                                         knowledge_node_ids=["onboarding"])]),
        s.BeliefState(probabilities={"a": 0.25, "b": 0.75}, turn_index=2),
        move,
        s.PlanResult(move=move, candidates=[s.ScoredMove(move=move, score=0.4, visits=3)], tree={"root": []}),
        turn,
        transcript,
        s.ToolSpec(name="send_onboarding_link", access="write", system="Messaging (mock)", description="mock"),
        call, result, decision,
        s.DialogueState(card=card, belief=s.BeliefState(probabilities=card.starting_worries),
                        transcript=transcript, moves=[move], actions=[decision]),
        s.HandoffCard(mission_id=card.mission_id, merchant=card.merchant, reason="distress",
                      top_concerns={"hidden_charges": 0.6}, tried_moves=[move], summary="Wants a human"),
        s.TwinReply(text="Theek hai", willingness=0.6, patience=0.4, resolved=["hidden_charges"]),
    ]
    for model in models:
        round_trip(model)


def test_belief_must_be_a_distribution():
    with pytest.raises(ValidationError):
        s.BeliefState(probabilities={"a": 0.5, "b": 0.6})
    with pytest.raises(ValidationError):
        s.BeliefState(probabilities={})
    belief = s.BeliefState(probabilities={"b": 0.4, "a": 0.4, "c": 0.2})
    assert belief.top(2) == [("a", 0.4), ("b", 0.4)]


def test_card_priority_is_chance_times_value_and_prior_is_validated():
    card = sample_card(chance=0.5, value=3.0)
    assert card.priority == 1.5
    with pytest.raises(ValidationError):
        sample_card(starting_worries={"hidden_charges": 0.9})


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        s.ToolCall(tool="x", argz={})


def test_consent_counts_only_merchant_turns():
    state = sample_state()
    transcript = state.transcript
    transcript.turns.append(s.Turn(speaker="agent", text="Shall I send the link?"))
    transcript.consents.append(s.ConsentRecord(tool="send_onboarding_link", turn_index=0, utterance="x"))
    assert not transcript.has_consent("send_onboarding_link")
    transcript.turns.append(s.Turn(speaker="merchant", text="Haan, bhej do"))
    transcript.consents.append(s.ConsentRecord(tool="send_onboarding_link", turn_index=1, utterance="Haan, bhej do"))
    assert transcript.has_consent("send_onboarding_link")
    assert not transcript.has_consent("book_field_visit")


def test_contact_window_and_doors():
    window = s.ContactWindow(start_hour=14, end_hour=17)
    assert window.contains(15) and not window.contains(17)
    with pytest.raises(ValidationError):
        s.ContactWindow(start_hour=17, end_hour=14)
    assert set(s.TRIGGER_DOORS) == set(s.TriggerType)


def test_move_key_names_its_target():
    assert s.Move(type=s.MoveType.PROBE_CONCERN, concern="rental_cost").key() == "PROBE_CONCERN(rental_cost)"
    assert s.Move(type=s.MoveType.DISCLOSE_AND_GREET).key() == "DISCLOSE_AND_GREET"
