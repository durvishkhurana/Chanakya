"""REST API for manager insights (task B12), mounted with the mission APIs when MISSIONS_ENABLED is true."""

from fastapi import APIRouter

from chanakya.insights.insights import summarise
from chanakya.missions.churn import leaving_reasons
from chanakya.missions.runtime import get_runtime

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("")
async def insights() -> dict:
    """Worries found, the mission funnel, which moves worked, escalations and reasons for leaving, from the ledger."""
    runtime = get_runtime()
    ledger = runtime.ledger
    return summarise(ledger.store.list(), ledger.store.events(), runtime.handoffs.list(), leaving_reasons(ledger),
                     now=runtime.clock())
