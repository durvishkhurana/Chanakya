"""Explicit local call-me command with durable duplicate prevention."""

import argparse
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
from dotenv import load_dotenv
from twilio.base.exceptions import TwilioRestException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from backend.twilio_security import CALL_SID, TERMINAL_STATUSES, TwilioSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = PROJECT_ROOT / ".state" / "phone-calls.sqlite3"


def open_state(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS calls (request_id TEXT PRIMARY KEY, state TEXT NOT NULL, sid TEXT)")
    return db


def create_call(settings, client, request_id, state_path=DEFAULT_STATE):
    """Commit intent before dialing; unknown outcomes block all further dialing."""
    settings.validate()
    if not settings.enabled:
        raise ValueError("Set TWILIO_ENABLED=true before dialing")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request_id):
        raise ValueError("Request ID must be 1-64 letters, numbers, dashes, or underscores")
    with closing(open_state(state_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT * FROM calls WHERE request_id = ?", (request_id,)).fetchone()
        if previous:
            if previous["sid"]:
                return previous["sid"]
            raise RuntimeError("This request was already attempted. Check Twilio Console and reconcile it before retrying.")
        for row in db.execute("SELECT * FROM calls WHERE state IN ('pending', 'unknown', 'created')").fetchall():
            if not row["sid"]:
                raise RuntimeError("A previous call outcome is unknown. Reconcile it before making another call.")
            status = client.calls(row["sid"]).fetch().status
            if status not in TERMINAL_STATUSES:
                raise RuntimeError("An outbound call is already active. Wait for it to end.")
            db.execute("UPDATE calls SET state = 'finished' WHERE request_id = ?", (row["request_id"],))
        db.execute("INSERT INTO calls VALUES (?, 'pending', NULL)", (request_id,))
        db.commit()
        try:
            call = client.calls.create(
                to=settings.allowed_phone_number, from_=settings.phone_number,
                url=settings.url("/api/telephony/voice"), method="POST",
                status_callback=settings.url("/api/telephony/call-status"),
                status_callback_method="POST",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                time_limit=settings.max_call_seconds, timeout=30, record=False,
            )
            if not CALL_SID.fullmatch(call.sid):
                raise RuntimeError("Twilio returned an invalid call identifier")
        except Exception as error:  # noqa: BLE001 - Creation outcomes must survive network/process failures.
            state = "unknown"
            if isinstance(error, TwilioRestException) and 400 <= error.status < 500:
                state = "rejected"
            db.execute("UPDATE calls SET state = ? WHERE request_id = ?", (state, request_id))
            db.commit()
            raise RuntimeError(
                "Twilio rejected the call. Check Console for details." if state == "rejected"
                else "Call outcome is unknown. Check Twilio Console; do not redial until reconciled."
            ) from None
        db.execute("UPDATE calls SET state = 'created', sid = ? WHERE request_id = ?", (call.sid, request_id))
        db.commit()
        return call.sid


def reconcile(settings, client, request_id, state_path, *, call_sid=None, no_call_created=False):
    """User supplies the Console result after an ambiguous dial response."""
    if bool(call_sid) == bool(no_call_created):
        raise ValueError("Supply either --call-sid or --no-call-created after checking Console")
    if call_sid:
        if not CALL_SID.fullmatch(call_sid):
            raise ValueError("Invalid call SID")
        call = client.calls(call_sid).fetch()
        if call.to != settings.allowed_phone_number or call.from_ != settings.phone_number:
            raise ValueError("This call does not match the configured caller and recipient")
    with closing(open_state(state_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM calls WHERE request_id = ?", (request_id,)).fetchone()
        if not row or row["state"] not in {"pending", "unknown"}:
            raise ValueError("Only an unresolved request can be reconciled")
        db.execute("UPDATE calls SET state = ?, sid = ? WHERE request_id = ?",
                   ("created" if call_sid else "rejected", call_sid, request_id))
        db.commit()


def main():
    parser = argparse.ArgumentParser(description="Call your configured mobile and connect it to Chanakya.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--request-id", help="Unique ID for this call; repeating it never redials")
    action.add_argument("--resolve-request", help="Reconcile an unknown outcome after checking Twilio Console")
    parser.add_argument("--call-sid")
    parser.add_argument("--no-call-created", action="store_true")
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        settings = TwilioSettings.from_env()
        settings.validate()
        client = Client(settings.account_sid, settings.auth_token,
                        http_client=TwilioHttpClient(timeout=10, max_retries=0))
        if args.resolve_request:
            reconcile(settings, client, args.resolve_request, args.state_file,
                      call_sid=args.call_sid, no_call_created=args.no_call_created)
            print("Request reconciled.")
        else:
            if args.call_sid or args.no_call_created:
                raise ValueError("Resolution flags require --resolve-request")
            # Local readiness check avoids placing a call to a stopped/unconfigured backend.
            health = httpx.get("http://127.0.0.1:8000/api/health", timeout=3).json()
            if not health.get("telephony"):
                raise ValueError("Start the configured backend on port 8000 before dialing")
            sid = create_call(settings, client, args.request_id, args.state_file)
            print(f"Call request recorded: {sid}")
    except (ValueError, RuntimeError, sqlite3.Error) as error:
        print(str(error))
        return 1
    except Exception as error:  # noqa: BLE001 - Never print provider exceptions containing private request data.
        print(f"Call setup failed ({type(error).__name__}). No automatic retry was attempted.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
