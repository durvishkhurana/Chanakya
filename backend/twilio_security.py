"""Server-only configuration, signed requests, and bounded call admission."""

import asyncio
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from twilio.request_validator import RequestValidator

TERMINAL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}
STATUS_ORDER = {"queued": 0, "initiated": 1, "ringing": 2, "in-progress": 3}
CALL_SID = re.compile(r"CA[0-9a-fA-F]{32}\Z")
ACCOUNT_SID = re.compile(r"AC[0-9a-fA-F]{32}\Z")
PHONE_NUMBER = re.compile(r"\+[1-9][0-9]{7,14}\Z")


@dataclass(frozen=True)
class TwilioSettings:
    enabled: bool = False
    account_sid: str = ""
    auth_token: str = field(default="", repr=False)
    phone_number: str = field(default="", repr=False)
    allowed_phone_number: str = field(default="", repr=False)
    public_base_url: str = ""
    retrieval_provider: str = "llm_batch"
    max_concurrent_calls: int = 1
    max_call_seconds: int = 600

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.getenv("TWILIO_ENABLED", "false").lower() in {"true", "1", "yes"},
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
            phone_number=os.getenv("TWILIO_PHONE_NUMBER", "").strip(),
            allowed_phone_number=os.getenv("TWILIO_ALLOWED_PHONE_NUMBER", "").strip(),
            public_base_url=os.getenv("TWILIO_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            retrieval_provider=os.getenv("TWILIO_RETRIEVAL_PROVIDER", "llm_batch"),
            max_concurrent_calls=int(os.getenv("TWILIO_MAX_CONCURRENT_CALLS", "1")),
            max_call_seconds=int(os.getenv("TWILIO_MAX_CALL_SECONDS", "600")),
        )

    def validate(self):
        if not ACCOUNT_SID.fullmatch(self.account_sid) or not self.auth_token:
            raise ValueError("Configure TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
        if not PHONE_NUMBER.fullmatch(self.phone_number) or not PHONE_NUMBER.fullmatch(self.allowed_phone_number):
            raise ValueError("Configure both Twilio phone numbers in E.164 format")
        if self.allowed_phone_number.startswith("+91") and self.phone_number.startswith("+91"):
            raise ValueError("Calls to India require a non-Indian Twilio caller number")
        url = urlsplit(self.public_base_url)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment or url.port not in {None, 443}):
            raise ValueError("TWILIO_PUBLIC_BASE_URL must be an HTTPS origin without a path or query")
        if self.retrieval_provider not in {"decisions", "jev", "llm_batch"}:
            raise ValueError("Invalid TWILIO_RETRIEVAL_PROVIDER")
        if not 1 <= self.max_concurrent_calls <= 10 or not 30 <= self.max_call_seconds <= 3600:
            raise ValueError("Twilio call limits must be 1-10 calls and 30-3600 seconds")

    def url(self, path, *, websocket=False):
        base = self.public_base_url.rstrip("/")
        if websocket:
            base = "wss://" + base.removeprefix("https://")
        return base + path


def valid_signature(settings, path, signature, params=None, *, websocket=False, query=""):
    """Use configured public URLs, never client-supplied Host/forwarded headers."""
    if not signature or len(signature) > 128:
        return False
    validator = RequestValidator(settings.auth_token)
    suffix = ("?" + query) if query else ""
    urls = [settings.url(path, websocket=websocket) + suffix]
    if websocket:
        # Twilio's HTTP upgrade can be signed as its HTTPS or WSS representation.
        urls += [settings.url(path) + suffix]
        urls += [url + "/" for url in urls]
    return any(validator.validate(url, params or {}, signature) for url in urls)


@dataclass
class CallAdmission:
    call_sid: str
    token: str = field(repr=False)
    created_at: float
    account_sid: str = ""
    state: str = "queued"
    stream_sid: str | None = None
    finished_at: float | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)


class CallRegistry:
    """One event loop owns admission; duplicates cannot consume extra capacity."""

    def __init__(self, settings, clock=time.monotonic):
        self.settings = settings
        self.clock = clock
        self.calls: dict[str, CallAdmission] = {}

    def prune(self):
        now = self.clock()
        for sid, call in list(self.calls.items()):
            if call.finished_at is not None and now - call.finished_at > 300:
                del self.calls[sid]
            elif call.stream_sid is None and call.finished_at is None and now - call.created_at > 60:
                self.finish(sid)

    def reserve(self, params):
        self.prune()
        sid = params.get("CallSid", "")
        if params.get("AccountSid") != self.settings.account_sid or not CALL_SID.fullmatch(sid):
            raise PermissionError("Unknown account or call")
        if params.get("Direction") == "inbound":
            allowed = (params.get("From") == self.settings.allowed_phone_number
                       and params.get("To") == self.settings.phone_number)
        elif params.get("Direction") == "outbound-api":
            allowed = (params.get("To") == self.settings.allowed_phone_number
                       and params.get("From") == self.settings.phone_number)
        else:
            allowed = False
        if not allowed:
            raise PermissionError("Caller or destination is not allowed")
        if sid in self.calls:
            call = self.calls[sid]
            if call.finished_at is not None:
                raise PermissionError("Call already ended")
            return call
        if sum(c.finished_at is None for c in self.calls.values()) >= self.settings.max_concurrent_calls:
            raise OverflowError("Chanakya is already on a call")
        if len(self.calls) >= 1000:
            raise OverflowError("Call admission history is full")
        call = CallAdmission(sid, secrets.token_urlsafe(24), self.clock(), self.settings.account_sid)
        self.calls[sid] = call
        return call

    def attach(self, start):
        self.prune()
        call = self.calls.get(start.get("callSid"))
        parameters = start.get("customParameters", {})
        if not isinstance(parameters, dict):
            raise PermissionError("Invalid stream parameters")
        token = parameters.get("session", "")
        if (call is None or call.finished_at is not None or call.stream_sid is not None
                or start.get("accountSid") != self.settings.account_sid
                or not isinstance(token, str) or not secrets.compare_digest(token, call.token)):
            raise PermissionError("Invalid or reused stream admission")
        stream_sid = start.get("streamSid", "")
        if not re.fullmatch(r"MZ[0-9a-fA-F]{32}", stream_sid):
            raise PermissionError("Invalid stream identifier")
        if start.get("mediaFormat") != {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}:
            raise ValueError("Only mono 8 kHz mu-law media is supported")
        if start.get("tracks") != ["inbound"]:
            raise ValueError("Expected bidirectional caller audio")
        call.stream_sid = stream_sid
        call.state = "in-progress"
        return call

    def update(self, sid, status):
        self.prune()
        call = self.calls.get(sid)
        if not call or call.finished_at is not None:
            return
        if status in TERMINAL_STATUSES:
            self.finish(sid, status)
        elif status in STATUS_ORDER and STATUS_ORDER[status] >= STATUS_ORDER.get(call.state, 0):
            call.state = status

    def finish(self, sid, status="completed"):
        call = self.calls.get(sid)
        if call and call.finished_at is None:
            call.state = status
            call.finished_at = self.clock()
            call.stop.set()

    def shutdown(self):
        for sid in self.calls:
            self.finish(sid)
