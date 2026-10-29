"""End-to-end run of Track B against a live backend: both demo flows plus the safety refusals.

Start a backend with a fresh state, then run this script:

    MISSIONS_ENABLED=true CALLING_HOURS=0-24 CHANAKYA_DB_PATH=/tmp/chanakya-e2e/ledger.db \
        .venv/bin/python -m uvicorn backend.main:app --port 8767
    .venv/bin/python scripts/demo/e2e_track_b.py http://127.0.0.1:8767

It expects an empty ledger (it loads the demo feed itself) and exits non-zero if any check fails.
"""

import sys

import httpx

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767"
h = httpx.Client(base_url=B, timeout=15)
checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


def post(path, body=None):
    r = h.post(path, json=body)
    return r.status_code, (r.json() if r.content else {})


def event(mid, kind, payload):
    return post(f"/api/missions/{mid}/events", {"kind": kind, "payload": payload})


def submit(mid, tool, **args):
    args.setdefault("merchant_id", "mer_ramesh")
    return post("/api/actions/submit", {"mission_id": mid, "tool": tool, "args": args})[1]


# Door 2 and Door 3: the demo feed
_, feed = post("/api/missions/signals/demo-feed")
check("demo feed opens 6 missions through all three doors", feed.get("created") == 6, str(feed))
missions = h.get("/api/missions").json()
check("do-not-call merchant is closed, never queued",
      any(m["mission"]["outcome"] == "do-not-call" and m["queue"] is None for m in missions))

# Door 1: a callback request from the mock product page
_, cb = post("/api/missions/signals", {"merchant_id": "mer_ramesh", "kind": "callback_request", "door": "merchant",
                                       "source": "mock product page", "details": {"product": "soundbox"}})
mid = cb["mission"]["id"]
card = cb["mission"]["card"]
check("callback opens a mission card with why-now and starting worries",
      card["why_now"] == "Requested a callback on the Soundbox page" and card["starting_worries"]["hidden_charges"] == 0.5)
check("callback is first in the queue", h.get("/api/missions/queue/next").json()["mission"]["id"] == mid)

for state in ("CONTACTING", "IN_CONVERSATION"):
    post(f"/api/missions/{mid}/advance", {"state": state})
check("write blocked before AI disclosure", submit(mid, "send_onboarding_link", product="soundbox")["reason"] == "AI disclosure not recorded")
event(mid, "ai_disclosed", {"text": "Main Chanakya hoon, ek AI assistant"})
check("write blocked before explicit consent", submit(mid, "send_onboarding_link", product="soundbox")["reason"] == "no explicit consent for this action")
event(mid, "turn_completed", {"speaker": "merchant", "text": "Kitna katega?", "language": "hi-IN", "move": None, "cues": {}})
event(mid, "belief_updated", {"probabilities": {"hidden_charges": 0.62, "competitor_qr": 0.29, "just_busy": 0.09}, "turn": 1})
event(mid, "consent_given", {"tools": ["send_onboarding_link", "send_summary"], "utterance": "Haan, dono theek hai"})
check("OTP text blocked even with consent", submit(mid, "send_summary", text="Apna OTP batayein")["reason"] == "arguments mention sensitive data")
check("invented tool rejected", submit(mid, "give_free_rental")["verdict"] == "rejected")
post(f"/api/missions/{mid}/advance", {"state": "ACTION_PENDING"})
sent = submit(mid, "send_onboarding_link", product="soundbox")
check("onboarding link sent after consent", sent["verdict"] == "executed", sent.get("result", {}).get("data", {}).get("link", ""))
check("mission waits for the merchant", h.get(f"/api/missions/{mid}").json()["mission"]["state"] == "AWAITING_CONFIRMATION")
outbox = h.get("/api/actions/outbox", params={"mission_id": mid}).json()
check("SMS with the link is in the mock outbox", outbox and outbox[0]["link"] == sent["result"]["data"]["link"])

sid = sent["result"]["data"]["session_id"]
_, done = post(f"/api/demo/onboarding/{sid}/complete")
check("merchant completes the mock onboarding page", done["session"]["status"] == "completed" and done["verified_missions"] == [mid])
final = h.get(f"/api/missions/{mid}").json()
check("mission DONE, verified by the system", final["mission"]["state"] == "DONE" and "verified" in final["mission"]["outcome"])
check("ledger carries every step", len(final["events"]) >= 15, f"{len(final['events'])} events")
audit = [d["verdict"] for d in h.get(f"/api/actions/audit/{mid}").json()]
check("audit trail shows blocked, rejected and executed attempts", {"blocked", "rejected", "executed"} <= set(audit), str(audit))

# Hand-off: a retention mission where the merchant gets upset
lakshmi = next(m["mission"] for m in missions if m["mission"]["card"]["merchant_id"] == "mer_lakshmi")
for state in ("CONTACTING", "IN_CONVERSATION"):
    post(f"/api/missions/{lakshmi['id']}/advance", {"state": state})
event(lakshmi["id"], "turn_completed", {"speaker": "merchant", "text": "My settlement is stuck and you call about rental?", "language": "en-IN", "move": None, "cues": {}})
_, ho = post("/api/handoffs/escalate", {"mission_id": lakshmi["id"], "reason": "merchant distressed about a settlement", "urgent": True})
check("distressed merchant handed to a person with a context card", ho.get("urgent") and ho.get("status") == "open" and ho.get("summary"))
post(f"/api/handoffs/{ho['id']}/claim", {"agent": "Sunita"})
_, res = post(f"/api/handoffs/{ho['id']}/resolve", {"resolution": "Settlement released; merchant keeps the Soundbox"})
check("person claims and resolves the hand-off", res.get("status") == "resolved")

print(f"\n{sum(checks)}/{len(checks)} checks passed")
sys.exit(0 if all(checks) else 1)
