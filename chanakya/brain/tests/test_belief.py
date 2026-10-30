import asyncio
import json

import pytest

from chanakya.brain.belief import BayesianBeliefTracker, LexicalScorer, LLMScorer
from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts.fakes import FakeLLM, InMemoryMissionStore, RecordingEventBus
from chanakya.brain.contracts.interfaces import BeliefTracker
from chanakya.brain.contracts.llm import LLMError
from chanakya.brain.contracts.schemas import TriggerType, Turn
from chanakya.brain.cues import hesitation

BANK = default_bank()


def merchant(text, pause=None, duration=None):
    return Turn(speaker="merchant", text=text, pause_before_ms=pause, duration_ms=duration)


def run(tracker, prior, *turns):
    belief = tracker.start(prior)
    history = []

    async def go():
        nonlocal belief
        for turn in turns:
            history.append(turn)
            belief = await tracker.update(belief, turn, history)
        return belief

    return asyncio.run(go())


@pytest.mark.parametrize("text,expected", [
    ("Koi hidden charge toh nahi hai na?", "hidden_charges"),
    ("Iska monthly rent kitna padega?", "rental_cost"),
    ("Mere paas pehle se PhonePe ka QR laga hua hai.", "competitor_qr"),
    ("मेरे ग्राहक तो कैश देते हैं।", "customers_pay_cash"),
    ("ਹੁਣੇ ਦੁਕਾਨ ਤੇ ਗਾਹਕ ਹਨ, ਬਾਅਦ ਵਿੱਚ ਗੱਲ ਕਰੋ।", "just_busy"),
    ("Har card swipe pe kitna katega?", "per_swipe_charges"),
    ("Aap sach mein Paytm se ho? Aise calls pe bharosa nahi hota.", "trust_in_caller"),
    ("Machine baar baar band ho jaati hai, theek se kaam nahi karti.", "device_issue"),
])
def test_scripted_utterances_move_the_right_concern_to_the_top(text, expected):
    tracker = BayesianBeliefTracker(BANK)
    uniform = {cid: 1.0 for cid in BANK.ids}
    belief = run(tracker, uniform, merchant(text))
    assert belief.top(1)[0][0] == expected


def test_later_inside_a_charges_question_is_not_a_busy_merchant():
    # "Baad mein" here means "charged later", not "call me later"; the cue used to tie just_busy with the asked worries.
    belief = run(BayesianBeliefTracker(BANK), {cid: 1.0 for cid in BANK.ids},
                 merchant("Aur iska kiraya kitna hai? Baad mein koi extra charge toh nahi katega?"))
    top = [cid for cid, _ in belief.top(2)]
    assert set(top) == {"rental_cost", "hidden_charges"}
    assert belief.probabilities["just_busy"] < 0.05


def test_belief_starts_from_the_mission_card_prior():
    tracker = BayesianBeliefTracker(BANK)
    belief = tracker.start(BANK.priors[TriggerType.SOUNDBOX_UNUSED])
    assert [cid for cid, _ in belief.top(3)] == ["rental_cost", "customers_pay_cash", "device_issue"]
    assert set(belief.probabilities) == set(BANK.ids)


def test_evidence_overrides_a_wrong_prior_within_two_turns():
    tracker = BayesianBeliefTracker(BANK)
    prior = BANK.priors[TriggerType.UPI_RISING_NO_SOUNDBOX]  # competitor_qr first
    belief = run(tracker, prior, merchant("Bhai details ka kya karoge?"),
                 merchant("Main apne documents phone pe nahi dunga."))
    assert belief.top(1)[0][0] == "data_privacy"


def test_neutral_turns_and_agent_turns_barely_move_the_belief():
    tracker = BayesianBeliefTracker(BANK)
    prior = BANK.priors[TriggerType.CALLBACK_REQUEST]
    start = tracker.start(prior)
    after = run(tracker, prior, Turn(speaker="agent", text="Koi hidden charge nahi hai"), merchant("Ji."))
    assert after.top(1)[0][0] == start.top(1)[0][0]
    assert after.turn_index == 2


def test_decay_fades_a_stale_concern():
    tracker = BayesianBeliefTracker(BANK, decay=0.3)
    prior = {"hidden_charges": 1.0}
    belief = run(tracker, prior, merchant("Ji."), merchant("Ji."), merchant("Ji."))
    assert belief.probabilities["hidden_charges"] < tracker.start(prior).probabilities["hidden_charges"]


def test_hesitation_cues_from_pause_fillers_and_slow_speech():
    fluent = hesitation(merchant("Haan bilkul, bhej dijiye link.", pause=200, duration=1500))
    halting = hesitation(merchant("Hmm... matlab... dekhiye, haan.", pause=3200, duration=6000))
    deflect = hesitation(merchant("Haan.", pause=2500))
    assert fluent.score < 0.2 < halting.score
    assert deflect.deflection and not fluent.deflection


def test_hesitation_tilts_belief_toward_unspoken_worries():
    tracker = BayesianBeliefTracker(BANK)
    prior = {"hidden_charges": 0.5, "just_busy": 0.5}
    calm = run(tracker, prior, merchant("Achha.", pause=100))
    halting = run(tracker, prior, merchant("Hmm... achha...", pause=3500, duration=4000))
    assert halting.probabilities["hidden_charges"] > calm.probabilities["hidden_charges"]


def test_belief_updated_events_carry_latency_and_are_persisted():
    store = InMemoryMissionStore()
    bus = RecordingEventBus(store)
    tracker = BayesianBeliefTracker(BANK, bus=bus, mission_id="m_test")
    run(tracker, BANK.prior_for(TriggerType.CALLBACK_REQUEST), merchant("Rent kitna hai?"))
    assert [e.kind for e in bus.published] == ["BeliefUpdated"]
    event = bus.published[0]
    assert event.latency_ms >= 0 and event.belief.top(1)[0][0] == "rental_cost"
    assert store.events("m_test")[0].kind == "BeliefUpdated"
    assert isinstance(tracker, BeliefTracker)


def test_llm_scorer_reads_scores_and_falls_back_offline():
    def respond(role, messages):
        assert role == "rollout" and "Latest merchant utterance" in messages[0]["content"]
        return json.dumps({"scores": {"settlement_delay": 0.9, "made_up": 1.0}})

    scorer = LLMScorer(FakeLLM(respond), BANK)
    scores = asyncio.run(scorer.score("Paisa kab aayega?", []))
    assert scores["settlement_delay"] == 0.9 and "made_up" not in scores and set(scores) == set(BANK.ids)

    def broken(role, messages):
        raise LLMError("offline")

    fallback = asyncio.run(LLMScorer(FakeLLM(broken), BANK).score("Koi hidden charge?", []))
    assert fallback == asyncio.run(LexicalScorer(BANK).score("Koi hidden charge?", []))


def test_latency_is_recorded_for_every_update():
    tracker = BayesianBeliefTracker(BANK)
    run(tracker, {"hidden_charges": 1.0}, merchant("Koi hidden charge?"))
    assert tracker.last_latency_ms >= 0 and tracker.last_evidence["hidden_charges"] > 0



class CalibratedStub:
    """A scorer that says its scores are calibrated (it has base_rates), like the N1 embedding scorer."""

    def __init__(self, scores, base_rate=1 / 14):
        self.scores = scores
        self.base_rates = {cid: base_rate for cid in BANK.ids}

    async def score(self, text, history):
        return {cid: self.scores.get(cid, self.base_rates[cid]) for cid in BANK.ids}


def test_calibrated_scores_at_the_base_rate_leave_the_belief_where_it_was():
    prior = BANK.priors[TriggerType.CALLBACK_REQUEST]
    tracker = BayesianBeliefTracker(BANK, scorer=CalibratedStub({}), decay=0.0)
    start = tracker.start(prior)
    after = run(tracker, prior, merchant("Haan ji, boliye"))
    assert all(abs(after.probabilities[c] - start.probabilities[c]) < 1e-9 for c in BANK.ids)


def test_a_confident_calibrated_score_moves_the_belief_to_that_worry():
    prior = BANK.priors[TriggerType.CALLBACK_REQUEST]
    tracker = BayesianBeliefTracker(BANK, scorer=CalibratedStub({"rental_cost": 0.9}))
    after = run(tracker, prior, merchant("Har mahine kitna dena padega?"))
    assert max(after.probabilities, key=after.probabilities.get) == "rental_cost"
    assert after.probabilities["rental_cost"] > 0.5


def test_scorers_without_base_rates_keep_the_tuned_lexical_likelihood():
    tracker = BayesianBeliefTracker(BANK)
    cue = hesitation(merchant("kiraya"))
    evidence = {cid: 0.0 for cid in BANK.ids} | {"rental_cost": 0.5}
    from chanakya.brain.belief import EPSILON, SHARPNESS

    assert tracker.likelihood(evidence, cue)["rental_cost"] == pytest.approx((EPSILON + 0.5) ** SHARPNESS)
