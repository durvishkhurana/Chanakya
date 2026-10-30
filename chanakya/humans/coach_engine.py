"""Coach mode: the belief tracker and planner run silently on a human telecaller's live call.

The engine never speaks. After each merchant turn it suggests the next best move with a one-line
reason and publishes a ``CoachSuggestion`` event for the coach screen.
"""

from collections.abc import AsyncIterator, Iterable

from chanakya.brain.belief import BayesianBeliefTracker
from chanakya.brain.concern_bank import default_bank
from chanakya.brain.contracts.events import CoachSuggestion
from chanakya.brain.contracts.schemas import DialogueState, MissionCard, Move, MoveType, Transcript, Turn
from chanakya.brain.planner_nrpa import NRPAPlanner

REASONS = {
    MoveType.DISCOVER_NEED: "Ask how their customers pay before pitching.",
    MoveType.PROBE_CONCERN: "They may be worried about {concern}; ask gently.",
    MoveType.RESOLVE_CONCERN: "Answer their worry about {concern} with the official source; quote no price.",
    MoveType.RECOMMEND: "They seem ready: recommend {product} for what they said.",
    MoveType.CONFIRM_CONSENT: "Ask a clear yes before sending anything ({tool}).",
    MoveType.TAKE_ACTION: "They clearly agreed: go ahead with {tool}.",
    MoveType.SCHEDULE_FOLLOWUP: "They are busy: offer a call back at a time they choose.",
    MoveType.ESCALATE: "Signs of distress: hand over to a senior colleague now.",
    MoveType.END_CALL_POLITELY: "They said no: thank them and close politely.",
    MoveType.DISCLOSE_AND_GREET: "Introduce yourself and the purpose of the call.",
}


def reason_for(move: Move, likelihood: float | None) -> str:
    """One plain line telling the telecaller why this move."""
    text = REASONS[move.type].format(concern=(move.concern or "").replace("_", " "), product=move.product or "",
                                     tool=(move.tool or "").replace("_", " "))
    if move.type in {MoveType.PROBE_CONCERN, MoveType.RESOLVE_CONCERN} and likelihood is not None:
        text += f" ({likelihood:.0%} likely)"
    return text


class CoachEngine:
    """Follows a human-led call turn by turn and suggests moves; it has no voice and takes no actions."""

    def __init__(self, card: MissionCard, planner=None, scorer=None, bus=None):
        self.bank = default_bank()
        self.planner = planner or NRPAPlanner(self.bank)
        self.tracker = BayesianBeliefTracker(self.bank, scorer=scorer, bus=bus, mission_id=card.mission_id)
        self.bus = bus
        # A human telecaller is not an AI; the disclosure rule is for Chanakya's own calls.
        self.state = DialogueState(card=card, belief=self.tracker.start(card.starting_worries),
                                   transcript=Transcript(mission_id=card.mission_id, disclosed_ai=True))
        self.state.moves.append(Move(type=MoveType.DISCLOSE_AND_GREET, reason="human greeting"))
        self.last_plan = None  # the latest look-ahead result, for the value estimate on the coach screen

    async def observe(self, turn: Turn) -> CoachSuggestion | None:
        """Fold in one turn; after a merchant turn, return the suggestion for the telecaller."""
        self.state.transcript.turns.append(turn)
        if turn.speaker != "merchant":
            if turn.move is not None:
                self.state.moves.append(turn.move)
            return None
        self.state.belief = await self.tracker.update(self.state.belief, turn, self.state.transcript.turns)
        plan = await self.planner.plan(self.state)
        self.last_plan = plan
        move = plan.move
        if move.type == MoveType.DISCLOSE_AND_GREET:
            move = Move(type=MoveType.DISCOVER_NEED)
        likelihood = self.state.belief.probabilities.get(move.concern) if move.concern else None
        suggestion = CoachSuggestion(mission_id=self.state.card.mission_id, move=move,
                                     reason=reason_for(move, likelihood))
        if self.bus is not None:
            await self.bus.publish(suggestion)
        return suggestion

    async def stream(self, turns: Iterable[Turn]) -> AsyncIterator[CoachSuggestion]:
        """Suggestions for a recorded or live sequence of turns."""
        for turn in turns:
            suggestion = await self.observe(turn)
            if suggestion is not None:
                yield suggestion
