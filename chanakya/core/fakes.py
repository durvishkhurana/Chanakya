"""In-memory fakes for every interface. Both tracks use these in tests until the real module merges."""

from __future__ import annotations

from collections.abc import Callable

from chanakya.core.interfaces import UnknownToolError
from chanakya.core.llm import FakeLLM
from chanakya.core.schemas import (
    ActionDecision,
    BeliefState,
    EventKind,
    Mission,
    MissionCard,
    MissionEvent,
    MissionState,
    Move,
    MoveType,
    PlanContext,
    PlanResult,
    ScoredMove,
    ToolCall,
    ToolInfo,
    ToolKind,
    ToolResult,
    Transcript,
    Turn,
    TwinReply,
    Verdict,
    utcnow,
)

__all__ = [
    "FakeBeliefTracker",
    "FakeLLM",
    "FakeMerchantTwin",
    "FakePlanner",
    "FakeRealizer",
    "FakeSafetyGate",
    "FakeToolRegistry",
    "InMemoryMissionStore",
]


class InMemoryMissionStore:
    """Dict-backed store with the same sequencing rules as the SQLite one; no state-machine checks."""

    def __init__(self) -> None:
        self.missions: dict[str, Mission] = {}
        self._events: list[MissionEvent] = []

    def create(self, mission: Mission) -> Mission:
        self.missions[mission.id] = mission
        return mission

    def get(self, mission_id: str) -> Mission | None:
        return self.missions.get(mission_id)

    def list(self, states: set[MissionState] | None = None) -> list[Mission]:
        return [m for m in self.missions.values() if states is None or m.state in states]

    def save(self, mission: Mission) -> Mission:
        mission = mission.model_copy(update={"updated_at": utcnow()})
        self.missions[mission.id] = mission
        return mission

    def append(self, event: MissionEvent) -> MissionEvent:
        seq = sum(1 for e in self._events if e.mission_id == event.mission_id) + 1
        stored = event.model_copy(update={"seq": seq})
        self._events.append(stored)
        return stored

    def events(self, mission_id: str | None = None, after_seq: int = 0) -> list[MissionEvent]:
        return [e for e in self._events if (mission_id is None or e.mission_id == mission_id) and e.seq > after_seq]


class FakeBeliefTracker:
    """Starts from the card's starting worries and never changes its mind."""

    def initial(self, card: MissionCard) -> BeliefState:
        return BeliefState(probabilities=card.starting_worries or {"unknown": 1.0})

    async def update(self, belief: BeliefState, turn: Turn, transcript: Transcript) -> BeliefState:
        return belief.model_copy(update={"turn": belief.turn + 1})


class FakePlanner:
    """Plays a fixed script of moves, then ends the call politely."""

    def __init__(self, script: list[Move] | None = None, allow_writes: bool = True):
        self.script = list(script or [Move(type=MoveType.DISCLOSE_AND_GREET)])
        self.allow_writes = allow_writes

    async def plan(self, context: PlanContext) -> PlanResult:
        move = self.script.pop(0) if self.script else Move(type=MoveType.END_CALL_POLITELY)
        return PlanResult(chosen=move, candidates=[ScoredMove(move=move, score=1.0, visits=1)])

    async def reconsider(self, context: PlanContext, call: ToolCall) -> bool:
        return self.allow_writes


class FakeRealizer:
    async def realize(self, move: Move, context: PlanContext) -> str:
        return f"[{move.type.value}]"


class FakeToolRegistry:
    """Registry over plain handler functions; unknown names raise UnknownToolError."""

    def __init__(self, tools: dict[str, tuple[ToolInfo, Callable[[dict], dict]]] | None = None):
        self._tools = dict(tools or {})

    def tools(self) -> list[ToolInfo]:
        return [info for info, _ in self._tools.values()]

    def get(self, name: str) -> ToolInfo | None:
        entry = self._tools.get(name)
        return entry[0] if entry else None

    def validate(self, call: ToolCall) -> ToolCall:
        if call.tool not in self._tools:
            raise UnknownToolError(call.tool)
        return call

    def execute(self, call: ToolCall) -> ToolResult:
        info, handler = self._tools[self.validate(call).tool]
        return ToolResult(call_id=call.id, tool=info.name, ok=True, data=handler(call.args))


class FakeSafetyGate:
    """Reads always run; writes run only after a CONSENT_GIVEN event in the mission's ledger."""

    def __init__(self, registry: FakeToolRegistry, store: InMemoryMissionStore):
        self.registry = registry
        self.store = store

    async def submit(self, call: ToolCall) -> ActionDecision:
        info = self.registry.get(call.tool)
        if info is None:
            decision = ActionDecision(call=call, verdict=Verdict.REJECTED, reason="unknown tool")
        elif info.kind == ToolKind.WRITE and not any(
            e.kind == EventKind.CONSENT_GIVEN for e in self.store.events(call.mission_id)
        ):
            decision = ActionDecision(call=call, verdict=Verdict.BLOCKED, reason="no consent", kind=info.kind)
        else:
            result = self.registry.execute(call)
            decision = ActionDecision(call=call, verdict=Verdict.EXECUTED, reason="ok", kind=info.kind, result=result)
        self.store.append(MissionEvent.of(call.mission_id, EventKind.ACTION_DECISION, decision))
        return decision


class FakeMerchantTwin:
    """Replies from a script; hangs up when the script runs out."""

    def __init__(self, replies: list[TwinReply] | None = None):
        self.replies = list(replies or [])

    async def respond(self, transcript: Transcript, agent_text: str) -> TwinReply:
        if not self.replies:
            return TwinReply(text="Theek hai, rakhta hoon.", willingness=0.0, ended=True)
        return self.replies.pop(0)
