"""Email each onboarding link Chanakya sends on a live call to one allowed inbox, so it reaches a real phone.

Off unless LINK_EMAIL_ENABLED is on. It only ever writes to LINK_EMAIL_TO, never to a merchant, and skips
demo scenarios, which are simulations.
"""

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

from backend.phone_link import frontend_port, tunnel
from chanakya.brain.calls_api import scenario_running
from chanakya.core.schemas import EventKind, MissionEvent

logger = logging.getLogger(__name__)
REQUIRED = ("LINK_EMAIL_TO", "SMTP_USER", "SMTP_PASSWORD")
SUBJECT = "Chanakya demo: your onboarding link (mock)"
FOOTER = "This is a demo on mock systems. It is not affiliated with Paytm."


def missing_settings() -> list[str]:
    """The settings an email needs that are blank in the environment."""
    return [name for name in REQUIRED if not os.getenv(name, "").strip()]


def public_url(link: str) -> str:
    """The link as a phone can open it: through the phone link when it is open, else on the laptop."""
    return (tunnel.status()["url"] or f"http://localhost:{frontend_port()}") + link


def message(event: MissionEvent) -> EmailMessage | None:
    """The email for an onboarding link sent on a live call, or None for any other event."""
    payload = event.payload
    data = (payload.get("result") or {}).get("data") or {}
    if (event.kind != EventKind.ACTION_DECISION or payload.get("verdict") != "executed"
            or (payload.get("call") or {}).get("tool") != "send_onboarding_link" or not data.get("link")
            or event.mission_id in scenario_running):
        return None
    url = public_url(data["link"])
    mail = EmailMessage()
    mail["Subject"] = SUBJECT
    mail["From"] = os.environ["SMTP_USER"]
    mail["To"] = os.environ["LINK_EMAIL_TO"]
    body = data.get("body", "").replace(data["link"], url) or url
    mail.set_content(f"{body}\n\n{FOOTER}\n")
    return mail


def send(mail: EmailMessage) -> None:
    """Send one email over SMTP with STARTTLS (Gmail by default)."""
    host, port = os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(mail)


def start(bus) -> asyncio.Task | None:
    """Start emailing links, or log which settings are blank and stay off."""
    if missing := missing_settings():
        logger.error("LINK_EMAIL_ENABLED is on but %s is blank, so links are not emailed", ", ".join(missing))
        return None
    logger.info("Onboarding links sent on live calls are emailed to LINK_EMAIL_TO")
    return asyncio.create_task(watch(bus))


async def watch(bus) -> None:
    """Email every onboarding link sent on a live call, until cancelled. A failed email never stops the call."""
    subscription = bus.subscribe()
    try:
        async for event in subscription:
            mail = message(event)
            if mail is None:
                continue
            try:
                await asyncio.to_thread(send, mail)
                logger.info("Emailed the onboarding link for mission %s", event.mission_id)
            except (OSError, smtplib.SMTPException) as error:
                logger.error("Could not email the onboarding link for mission %s: %s", event.mission_id, error)
    finally:
        await subscription.aclose()
