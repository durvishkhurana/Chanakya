"""In-memory fakes for every interface. Both tracks use these in tests; none of them touch a network."""

from collections.abc import Callable

from .config import Role
from .events import Event, Handler, InProcessEventBus
from .llm import Message
from .schemas import (
    TERMINAL_STATES,
    ActionDecision,
    BeliefState,
    DialogueState,
    Mission,
    MissionCard,
    MissionEvent,
    MissionState,
    Move,
    MoveType,
    PlanResult,
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    TwinReply,
    utc_now,
)


class FakeLLM:
    """Returns scripted replies. ``responder`` gets ``(role, messages)``; a list is consumed in order."""

    def __init__(self, responder: Callable[[Role, list[Message]], str] | list[str] | str = "{}"):
        self.responder = responder
        self.calls: list[dict] = []

    async def complete(
        self, role: Role, messages: list[Message], *, json_mode: bool = False,
        temperature: float = 0.0, seed: int | None = None, max_tokens: int = 800,
    ) -> str:
        """Record the call and return the next scripted reply."""
        self.calls.append({"role": role, "messages": messages, "json_mode": json_mode, "seed": seed})
        if callable(self.responder):
            return self.responder(role, messages)
        if isinstance(self.responder, list):
            if not self.responder:
                raise AssertionError("FakeLLM ran out of scripted replies")
            return self.responder.pop(0)
        return self.responder


class FakeBeliefTracker:
    """Starts from the prior and leaves it unchanged, counting turns."""

    def start(self, prior: dict[str, float]) -> BeliefState:
        total = sum(prior.values())
        return BeliefState(probabilities={key: value / total for key, value in prior.items()})

    async def update(self, belief: BeliefState, turn: Turn, history: list[Turn]) -> BeliefState:
        return belief.model_copy(update={"turn_index": belief.turn_index + 1})


class FakePlanner:
    """Plays scripted moves in order, then ends the call politely. Reconsideration always allows."""

    def __init__(self, moves: list[Move] | None = None, allow_writes: bool = True):
        self.moves = list(moves or [])
        self.allow_writes = allow_writes

    async def plan(self, state: DialogueState) -> PlanResult:
        move = self.moves.pop(0) if self.moves else Move(type=MoveType.END_CALL_POLITELY)
        return PlanResult(move=move)

    async def reconsider(self, state: DialogueState, call: ToolCall) -> bool:
        return self.allow_writes


class FakeRealizer:
    """Renders a move as a fixed English sentence naming the move."""

    async def realize(self, move: Move, state: DialogueState) -> str:
        return f"[{move.key()}]"


MOCK_TOOLS = [
    ToolSpec(name="get_device_status", access="read", system="Devices (mock)",
             description="Mock device status lookup", args_schema={"merchant_id": "string"}),
    ToolSpec(name="send_onboarding_link", access="write", system="Messaging (mock)",
             description="Mock onboarding link to the allowlisted demo phone", args_schema={"merchant_id": "string"}),
    ToolSpec(name="book_field_visit", access="write", system="Field ops (mock)",
             description="Mock field visit booking", args_schema={"merchant_id": "string"}, high_risk=True),
]


class FakeToolRegistry:
    """Mock systems only: every known tool succeeds and echoes its arguments; unknown tools fail."""

    def __init__(self, tools: list[ToolSpec] | None = None):
        self.tools = {tool.name: tool for tool in (tools or MOCK_TOOLS)}
        self.executed: list[ToolCall] = []

    def get(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return list(self.tools.values())

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.tool not in self.tools:
            return ToolResult(call_id=call.call_id, ok=False, error="unknown_tool")
        self.executed.append(call)
        return ToolResult(call_id=call.call_id, ok=True, data={"mock": True, **call.args})


class FakeSafetyGate:
    """Rejects unknown tools and writes without consent; otherwise executes through the registry."""

    def __init__(self, registry: FakeToolRegistry | None = None):
        self.registry = registry or FakeToolRegistry()

    async def check(self, call: ToolCall, state: DialogueState) -> ActionDecision:
        spec = self.registry.get(call.tool)
        if spec is None:
            return ActionDecision(call=call, verdict="blocked", reason="unknown_tool")
        if spec.access == "write" and not state.transcript.has_consent(call.tool):
            return ActionDecision(call=call, verdict="blocked", reason="no_consent")
        result = await self.registry.execute(call)
        return ActionDecision(call=call, verdict="executed" if result.ok else "failed",
                              reason="ok" if result.ok else (result.error or "failed"), result=result)


class InMemoryMissionStore:
    """Keeps missions and the ledger in memory. Terminal missions cannot move again."""

    def __init__(self):
        self.missions: dict[str, Mission] = {}
        self.ledger: list[MissionEvent] = []

    def create(self, card: MissionCard) -> Mission:
        mission = Mission(card=card)
        self.missions[card.mission_id] = mission
        return mission

    def get(self, mission_id: str) -> Mission | None:
        return self.missions.get(mission_id)

    def advance(self, mission_id: str, state: MissionState, reason: str = "") -> Mission:
        mission = self.missions[mission_id]
        if mission.state in TERMINAL_STATES:
            raise ValueError(f"Mission {mission_id} is already {mission.state}")
        mission = mission.model_copy(update={"state": state, "updated_at": utc_now()})
        self.missions[mission_id] = mission
        return mission

    def append_event(self, event: MissionEvent) -> None:
        self.ledger.append(event)

    def events(self, mission_id: str | None = None) -> list[MissionEvent]:
        return [event for event in self.ledger if mission_id is None or event.mission_id == mission_id]


class FakeMerchantTwin:
    """Replies from a script; ends the call when the script runs out."""

    def __init__(self, replies: list[str] | None = None, opening: str = "Haan, boliye?"):
        self.replies = list(replies or [])
        self._opening = opening

    def opening(self) -> str:
        return self._opening

    async def respond(self, agent_text: str, move: Move | None) -> TwinReply:
        if not self.replies:
            return TwinReply(text="Theek hai, bye.", willingness=0.5, patience=0.0, ended=True)
        return TwinReply(text=self.replies.pop(0), willingness=0.5, patience=0.5)


def sample_card(**overrides) -> MissionCard:
    """A ready-made Door 1 sales mission card for tests (mock merchant, no real data)."""
    from .schemas import Door, Merchant, MissionKind, TriggerType

    fields = {
        "mission_id": "m_test",
        "merchant": Merchant(merchant_id="mer_test", name="Ramesh Kirana (mock)", business_type="kirana",
                             city="Jaipur", language="hi-IN"),
        "kind": MissionKind.SALES,
        "goal": "Sell Soundbox, then verified onboarding",
        "door": Door.MERCHANT,
        "trigger": TriggerType.CALLBACK_REQUEST,
        "why_now": "Requested a callback 30 seconds ago",
        "starting_worries": {"hidden_charges": 0.5, "competitor_qr": 0.3, "just_busy": 0.2},
        "chance": 0.6,
        "value": 1.0,
    }
    return MissionCard(**(fields | overrides))


def sample_state(card: MissionCard | None = None) -> DialogueState:
    """A fresh dialogue state for ``card`` with the belief set to its starting worries."""
    from .schemas import Transcript

    card = card or sample_card()
    return DialogueState(card=card, belief=BeliefState(probabilities=dict(card.starting_worries)),
                         transcript=Transcript(mission_id=card.mission_id))


class RecordingEventBus(InProcessEventBus):
    """An in-process bus that also keeps every published event for assertions."""

    def __init__(self, store=None):
        super().__init__(store)
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        await super().publish(event)

    def subscribe(self, kind: str | None, handler: Handler):
        return super().subscribe(kind, handler)
