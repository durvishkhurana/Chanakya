"""Emailing the onboarding link to the one allowed inbox. Never opens a real SMTP connection."""

import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

from backend import link_email
from chanakya.brain.calls_api import scenario_running
from chanakya.core.events import InProcessEventBus
from chanakya.core.fakes import InMemoryMissionStore
from chanakya.core.schemas import EventKind, MissionEvent

URL = "https://quiet-river-sample-words.trycloudflare.com"
SETTINGS = {"LINK_EMAIL_TO": "demo@example.com", "SMTP_USER": "sender@example.com", "SMTP_PASSWORD": "app-password"}


def link_sent(mission_id="m_live", verdict="executed", tool="send_onboarding_link"):
    return MissionEvent.of(mission_id, EventKind.ACTION_DECISION, {
        "call": {"tool": tool, "args": {"channel": "whatsapp"}}, "verdict": verdict, "reason": "ok",
        "result": {"data": {"link": "/demo/onboard/onb_1", "body": "Hello Anita\n/demo/onboard/onb_1\nReply STOP"}},
    })


@patch.dict(os.environ, SETTINGS)
class LinkEmailTests(unittest.IsolatedAsyncioTestCase):
    def test_the_email_goes_only_to_the_allowed_inbox_with_a_link_the_phone_can_open(self):
        with patch.object(link_email.tunnel, "status", return_value={"running": True, "url": URL}):
            mail = link_email.message(link_sent())
        self.assertEqual(mail["To"], "demo@example.com")
        self.assertIn(f"{URL}/demo/onboard/onb_1", mail.get_content())
        self.assertIn("not affiliated with Paytm", mail.get_content())

    def test_without_the_phone_link_the_email_points_at_the_laptop(self):
        with patch.object(link_email.tunnel, "status", return_value={"running": False, "url": None}):
            self.assertIn("http://localhost:3000/demo/onboard/onb_1", link_email.message(link_sent()).get_content())

    def test_blocked_actions_other_tools_and_demo_scenarios_send_nothing(self):
        self.assertIsNone(link_email.message(link_sent(verdict="blocked")))
        self.assertIsNone(link_email.message(link_sent(tool="send_onboarding_reminder")))
        self.assertIsNone(link_email.message(MissionEvent.of("m_live", EventKind.CONSENT_GIVEN, {})))
        scenario_running.add("m_scenario")
        try:
            self.assertIsNone(link_email.message(link_sent("m_scenario")))
        finally:
            scenario_running.discard("m_scenario")

    async def test_a_sent_link_is_emailed_and_a_failed_email_is_only_logged(self):
        bus = InProcessEventBus(InMemoryMissionStore())
        smtp = MagicMock()
        with patch("backend.link_email.smtplib.SMTP") as connect:
            connect.return_value.__enter__.return_value = smtp
            smtp.send_message.side_effect = [OSError("network down"), None]
            task = asyncio.create_task(link_email.watch(bus))
            await asyncio.sleep(0)
            with self.assertLogs("backend.link_email", "INFO") as logs:
                await bus.publish(link_sent())
                await bus.publish(link_sent())
                for _ in range(100):
                    if len(logs.output) == 2:
                        break
                    await asyncio.sleep(0.01)
            task.cancel()
        smtp.starttls.assert_called()
        smtp.login.assert_called_with("sender@example.com", "app-password")
        self.assertEqual(smtp.send_message.call_count, 2)
        self.assertIn("Could not email", logs.output[0])
        self.assertIn("Emailed the onboarding link", logs.output[1])

    def test_it_stays_off_when_a_setting_is_blank(self):
        with patch.dict(os.environ, {"SMTP_PASSWORD": ""}), self.assertLogs("backend.link_email", "ERROR"):
            self.assertIsNone(link_email.start(InProcessEventBus(InMemoryMissionStore())))


if __name__ == "__main__":
    unittest.main()
