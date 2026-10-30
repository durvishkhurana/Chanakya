"""Approval queue (task B10): high-risk actions wait for a person before they run, and everything is in the ledger.

A write tool listed in ``APPROVAL_TOOLS`` that passes every gate check (consent, calling hours, policy) is not run:
the gate returns ``Verdict.PENDING`` and this queue records ``approval_requested`` with the exact call. A person then
approves it, which runs the call through the full gate again with their name on it, or rejects it, which hands the
mission to a person to tell the merchant. A request still waiting after ``APPROVAL_TIMEOUT_MINUTES`` expires and is
handed to a person, urgently. Pending and decided requests are read back from the ledger, so there is no second store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from chanakya.core.schemas import ActionDecision, EventKind, MissionState, ToolCall, Verdict, new_id

S = MissionState


class ApprovalQueue:
    """Requests, decisions and timeouts for high-risk actions, all as mission ledger events."""

    def __init__(self, ledger, scheduler, handoffs, settings, clock, submit: Callable[..., Awaitable[ActionDecision]]):
        self.ledger = ledger
        self.scheduler = scheduler
        self.handoffs = handoffs
        self.settings = settings
        self.clock = clock
        self.submit = submit  # Runtime.submit, so an approved call takes the same path (gate, verifier) as any other
        self._lock = asyncio.Lock()  # one decision at a time, so a double click cannot run an action twice

    async def request(self, call: ToolCall) -> dict:
        """Record a pending request for ``call`` and schedule its timeout."""
        now = self.clock()
        expires = now + timedelta(minutes=self.settings.approval_timeout_minutes)
        mission = self.ledger.store.get(call.mission_id)
        payload = {"approval_id": new_id("ap"), "call": call.model_dump(mode="json"), "tool": call.tool,
                   "merchant_name": mission.card.merchant_name, "requested_at": now.isoformat(),
                   "expires_at": expires.isoformat()}
        await self.ledger.record(call.mission_id, EventKind.APPROVAL_REQUESTED, payload)
        await self.scheduler.schedule(call.mission_id, "approval_timeout", expires, approval_id=payload["approval_id"])
        return payload | {"status": "pending", "mission_id": call.mission_id}

    def list(self, status: str | None = None) -> list[dict]:
        """Every request with its status (pending, approved, rejected, expired), pending first then newest first."""
        events = self.ledger.store.events()
        requests, decisions, results = {}, {}, {}
        for event in events:
            if event.kind == EventKind.APPROVAL_REQUESTED:
                requests[event.payload["approval_id"]] = event.payload | {"mission_id": event.mission_id}
            elif event.kind == EventKind.APPROVAL_DECIDED:
                decisions[event.payload["approval_id"]] = event.payload | {"seq": event.seq}
        for approval_id, decision in decisions.items():
            # The approved call's own action decision is the first one for that mission and tool after the approval.
            results[approval_id] = next((e.payload for e in events if e.seq > decision["seq"] and e.kind == EventKind.ACTION_DECISION
                                         and e.mission_id == requests[approval_id]["mission_id"]
                                         and (e.payload.get("call") or {}).get("tool") == decision["tool"]), None)
        rows = []
        for approval_id, request in requests.items():
            decision, result = decisions.get(approval_id, {}), results.get(approval_id) or {}
            rows.append(request | {"status": decision.get("status", "pending"), "decided_by": decision.get("by"),
                                   "decided_at": decision.get("at"), "note": decision.get("note"),
                                   "verdict": result.get("verdict"), "verdict_reason": result.get("reason")})
        pending = [r for r in rows if r["status"] == "pending"]
        decided = sorted((r for r in rows if r["status"] != "pending"), key=lambda r: r["decided_at"] or "", reverse=True)
        return [r for r in pending + decided if status is None or r["status"] == status]

    def _pending(self, approval_id: str) -> dict:
        request = next((r for r in self.list() if r["approval_id"] == approval_id), None)
        if request is None:
            raise LookupError(f"unknown approval {approval_id}")
        if request["status"] != "pending":
            raise ValueError(f"approval {approval_id} is already {request['status']}")
        return request

    async def _decide(self, request: dict, status: str, by: str, note: str = "") -> None:
        await self.ledger.record(request["mission_id"], EventKind.APPROVAL_DECIDED, {
            "approval_id": request["approval_id"], "status": status, "by": by, "note": note,
            "at": self.clock().isoformat(), "tool": request["tool"]})

    async def approve(self, approval_id: str, by: str) -> dict:
        """Run the waiting call through the full gate with the approver's name; returns the request as decided."""
        async with self._lock:
            request = self._pending(approval_id)
            await self._decide(request, "approved", by)
        call = ToolCall.model_validate(request["call"])
        decision = await self.submit(call, approved_by=by)
        mission = self.ledger.store.get(call.mission_id)
        if decision.verdict == Verdict.EXECUTED:
            if mission.state == S.ACTION_PENDING:
                await self.ledger.advance(call.mission_id, S.AWAITING_CONFIRMATION, reason=f"{call.tool} approved by {by} and done")
        elif mission.is_open:
            # Approved, but the gate stopped it now (for example outside calling hours): a person takes it from here.
            await self.handoffs.escalate(call.mission_id, f"approved {call.tool} could not run: {decision.reason}")
        return next(r for r in self.list() if r["approval_id"] == approval_id)

    async def reject(self, approval_id: str, by: str, note: str = "") -> dict:
        """Refuse the call; a person tells the merchant, so the mission is handed over."""
        async with self._lock:
            request = self._pending(approval_id)
            await self._decide(request, "rejected", by, note)
        if self.ledger.store.get(request["mission_id"]).is_open:
            await self.handoffs.escalate(request["mission_id"], f"{request['tool']} rejected by {by}: {note or 'no reason given'}")
        return next(r for r in self.list() if r["approval_id"] == approval_id)

    async def expire(self, job) -> None:
        """Scheduler job: a request nobody decided in time goes to a person, urgently."""
        async with self._lock:
            try:
                request = self._pending(job.payload["approval_id"])
            except (LookupError, ValueError):
                return  # decided in time
            await self._decide(request, "expired", "timeout", f"no decision in {self.settings.approval_timeout_minutes} minutes")
        if self.ledger.store.get(request["mission_id"]).is_open:
            await self.handoffs.escalate(request["mission_id"],
                                         f"{request['tool']} approval timed out after {self.settings.approval_timeout_minutes} minutes",
                                         urgent=True)


router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class Decision(BaseModel):
    by: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=300)


def _queue() -> ApprovalQueue:
    from chanakya.missions.runtime import get_runtime

    return get_runtime().approvals


@router.get("")
async def list_approvals(status: str | None = None) -> list[dict]:
    """Approval requests, pending first."""
    return _queue().list(status)


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, decision: Decision) -> dict:
    """Approve a waiting action: it runs through the full gate, with the approver's name in the ledger."""
    return await _call(_queue().approve(approval_id, decision.by))


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, decision: Decision) -> dict:
    """Reject a waiting action; the mission goes to a person."""
    return await _call(_queue().reject(approval_id, decision.by, decision.note))


async def _call(coro) -> dict:
    try:
        return await coro
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
