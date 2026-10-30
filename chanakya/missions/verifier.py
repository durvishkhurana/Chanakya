"""Verification and follow-up: a mission is DONE only when a system confirms the outcome (docs/IDEA.md 3.8)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from chanakya.actions.gate import ActionGate
from chanakya.core.schemas import EventKind, MissionState, ToolCall, Verdict
from chanakya.missions.ledger import MissionLedger
from chanakya.missions.scheduler import Job, Scheduler

S = MissionState
ACTIVE_DEVICE = frozenset({"online", "active"})
PAYMENT_WINDOW = timedelta(days=14)


class OnboardingVerifier:
    """Checks onboarding after a link is sent, nudges when it is not done yet, and hands back to a call after that."""

    def __init__(self, ledger: MissionLedger, gate: ActionGate, scheduler: Scheduler,
                 verify_after: timedelta = timedelta(hours=2), nudge_after: timedelta = timedelta(days=1),
                 max_nudges: int = 2):
        self.ledger = ledger
        self.gate = gate
        self.scheduler = scheduler
        self.verify_after = verify_after
        self.nudge_after = nudge_after
        self.max_nudges = max_nudges
        self.handlers: dict = {}  # other job kinds by name, for example the approval queue's timeouts (B10)

    async def expect_onboarding(self, mission_id: str, session_id: str, link: str) -> None:
        """Call after ``send_onboarding_link`` executed: wait for the merchant, then verify."""
        mission = self.ledger.store.get(mission_id)
        if mission.state == S.ACTION_PENDING:
            await self.ledger.advance(mission_id, S.AWAITING_CONFIRMATION, reason="onboarding link sent")
        await self.scheduler.schedule(mission_id, "verify", self.scheduler.later(self.verify_after),
                                      session_id=session_id, link=link, nudges=0)

    async def run_due(self) -> list[Job]:
        """Run every job whose time has come; returns the jobs run."""
        jobs = self.scheduler.due()
        for job in jobs:
            self.scheduler.finish(job)
            await self._run(job)
        return jobs

    async def run_mission_now(self, mission_id: str) -> list[Job]:
        """Run this mission's pending jobs straight away, without moving the clock or touching other missions.

        Demo scenarios use it so a live backend's shared clock, and with it calling hours, stays where it is.
        """
        jobs = self.scheduler.pending(mission_id)
        for job in jobs:
            self.scheduler.finish(job)
            await self._run(job)
        return jobs

    async def _run(self, job: Job) -> None:
        mission = self.ledger.store.get(job.mission_id)
        if mission is None or not mission.is_open:
            return
        if job.kind == "verify":
            await self._verify(job)
        elif job.kind == "nudge":
            await self._nudge(job)
        elif job.kind == "winback_verify":
            await self._verify_winback(job)
        elif job.kind in self.handlers:
            await self.handlers[job.kind](job)

    async def check_now(self, session_id: str) -> list[str]:
        """Verify right away every mission waiting on this onboarding session (the onboarding page calls this)."""
        verified = []
        for job in self.scheduler.pending():
            if job.kind == "verify" and job.payload.get("session_id") == session_id:
                self.scheduler.finish(job)
                await self._verify(job)
                verified.append(job.mission_id)
        return verified

    async def _verify(self, job: Job) -> None:
        mission = self.ledger.store.get(job.mission_id)
        if mission.state != S.VERIFYING:
            await self.ledger.advance(mission.id, S.VERIFYING, reason="checking onboarding status")
        decision = await self.gate.submit(ToolCall(
            mission_id=mission.id, tool="get_onboarding_status",
            args={"merchant_id": mission.card.merchant_id, "session_id": job.payload["session_id"]},
        ))
        status = decision.result.data.get("status") if decision.verdict == Verdict.EXECUTED else "unknown"
        await self.ledger.record(mission.id, EventKind.VERIFICATION_CHECKED,
                                 {"session_id": job.payload["session_id"], "status": status, "verdict": decision.verdict})

        if status == "completed":
            self.scheduler.cancel_all(mission.id)
            await self.ledger.close(mission.id, S.DONE, outcome="onboarding completed (verified by the onboarding system)")
            return
        if job.payload.get("stop_contact"):
            await self.ledger.close(mission.id, S.CLOSED_NOT_INTERESTED,
                                    outcome="asked for no more reminders; onboarding not completed")
            return
        if job.payload["nudges"] < self.max_nudges:
            await self.ledger.advance(mission.id, S.AWAITING_CONFIRMATION, reason=f"onboarding {status}")
            await self.scheduler.schedule(mission.id, "nudge", self.scheduler.later(self.nudge_after), **job.payload)
            return
        # Back to the mission queue for a call; the queue holds it until the callback time (no job runner needed).
        await self.ledger.advance(mission.id, S.SCHEDULED, reason="still not onboarded after reminders; call again")
        await self.ledger.record(mission.id, EventKind.FOLLOWUP_SCHEDULED,
                                 {"kind": "callback", "due_at": self.scheduler.later(timedelta(hours=1)).isoformat(),
                                  **job.payload})

    # ── win-back: DONE only when a system shows the merchant is back ─────

    async def expect_winback(self, mission_id: str, ticket_id: str | None = None) -> None:
        """Call after a win-back fix ran (ticket, visit): check the systems later, never the call's words."""
        mission = self.ledger.store.get(mission_id)
        if mission.state == S.ACTION_PENDING:
            await self.ledger.advance(mission_id, S.AWAITING_CONFIRMATION, reason="fix requested; waiting for the systems")
        devices = await self._read(mission, "get_device_status")
        baseline = {d["id"]: d["status"] for d in devices.get("devices", [])}
        await self.scheduler.schedule(mission_id, "winback_verify", self.scheduler.later(self.verify_after),
                                      since=self.scheduler.clock().isoformat(), ticket_id=ticket_id,
                                      baseline=baseline, nudges=0)

    async def check_winback_now(self, ticket_id: str) -> list[str]:
        """Verify right away every win-back mission waiting on this ticket (the mock ticketing page calls this)."""
        verified = []
        for job in self.scheduler.pending():
            if job.kind == "winback_verify" and job.payload.get("ticket_id") == ticket_id:
                self.scheduler.finish(job)
                await self._verify_winback(job)
                verified.append(job.mission_id)
        return verified

    async def _read(self, mission, tool: str, **args) -> dict:
        args = args or {"merchant_id": mission.card.merchant_id}
        decision = await self.gate.submit(ToolCall(mission_id=mission.id, tool=tool, args=args))
        return decision.result.data if decision.verdict == Verdict.EXECUTED else {}

    async def winback_confirmation(self, mission, payload: dict) -> str | None:
        """What a system shows, if anything: the call's ticket resolved, a device active again, or a payment within
        14 days of the call. Every read goes through the gate, so the checks are in the audit trail."""
        if payload.get("ticket_id"):
            ticket = (await self._read(mission, "get_ticket_status", ticket_id=payload["ticket_id"])).get("ticket") or {}
            if ticket.get("status") == "resolved":
                return f"ticket {payload['ticket_id']} resolved (ticketing system)"
        baseline = payload.get("baseline") or {}
        for device in (await self._read(mission, "get_device_status")).get("devices", []):
            if device["status"] in ACTIVE_DEVICE and baseline.get(device["id"]) not in ACTIVE_DEVICE:
                return f"device {device['id']} is {device['status']} again (devices system)"
        since = datetime.fromisoformat(payload["since"])
        for device in (await self._read(mission, "get_device_usage")).get("devices", []):
            paid = device.get("last_payment_at")
            if paid and since <= datetime.fromisoformat(paid) <= since + PAYMENT_WINDOW:
                return f"device {device['id']} took a payment within 14 days of the call (devices system)"
        return None

    async def _verify_winback(self, job: Job) -> None:
        mission = self.ledger.store.get(job.mission_id)
        if mission.state != S.VERIFYING:
            await self.ledger.advance(mission.id, S.VERIFYING, reason="checking whether the merchant is back")
        confirmed = await self.winback_confirmation(mission, job.payload)
        await self.ledger.record(mission.id, EventKind.VERIFICATION_CHECKED,
                                 {"kind": "win_back", "status": "confirmed" if confirmed else "not yet",
                                  "evidence": confirmed})
        if confirmed:
            self.scheduler.cancel_all(mission.id)
            await self.ledger.close(mission.id, S.DONE, outcome=f"merchant is back: {confirmed}")
            return
        if job.payload["nudges"] < self.max_nudges:
            # A passive re-check: win-back sends no messages, because nobody agreed to receive any.
            await self.ledger.advance(mission.id, S.AWAITING_CONFIRMATION, reason="no system shows them back yet")
            await self.scheduler.schedule(mission.id, "winback_verify", self.scheduler.later(self.nudge_after),
                                          **(job.payload | {"nudges": job.payload["nudges"] + 1}))
            return
        await self.ledger.advance(mission.id, S.SCHEDULED, reason="still not back after re-checks; call again")
        await self.ledger.record(mission.id, EventKind.FOLLOWUP_SCHEDULED,
                                 {"kind": "callback", "due_at": self.scheduler.later(timedelta(hours=1)).isoformat()})

    async def _nudge(self, job: Job) -> None:
        mission = self.ledger.store.get(job.mission_id)
        # The reminder tool sends only its fixed template, so a yes to the link never approves free text.
        decision = await self.gate.submit(ToolCall(
            mission_id=mission.id, tool="send_onboarding_reminder",
            args={"merchant_id": mission.card.merchant_id, "session_id": job.payload["session_id"], "channel": "whatsapp"},
        ))
        if decision.verdict == Verdict.BLOCKED and decision.reason.startswith("outside calling hours"):
            await self.scheduler.schedule(mission.id, "nudge", self._next_calling_time(), **job.payload)
            return
        # Attempts count, not only successes, so a broken messaging system cannot cause endless retries.
        payload = job.payload | {"nudges": job.payload["nudges"] + 1}
        if decision.verdict == Verdict.BLOCKED and decision.reason == "merchant declined":
            payload |= {"nudges": self.max_nudges, "stop_contact": True}  # they said stop: one last passive check
        await self.scheduler.schedule(mission.id, "verify", self.scheduler.later(self.verify_after), **payload)

    def _next_calling_time(self) -> datetime:
        settings = self.gate.settings
        zone = ZoneInfo(settings.timezone)
        local = self.scheduler.clock().astimezone(zone)
        start = datetime.combine(local.date(), time(settings.calling_hours[0]), zone)
        return start if local < start else start + timedelta(days=1)
