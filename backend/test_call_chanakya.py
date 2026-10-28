import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from twilio.base.exceptions import TwilioRestException

from backend.call_chanakya import create_call, reconcile
from backend.test_twilio import CALL, SETTINGS


class OutboundCallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "calls.sqlite3"
        self.client = Mock()
        self.client.calls.create.return_value = SimpleNamespace(sid=CALL)

    def dial(self, request_id):
        return create_call(SETTINGS, self.client, request_id, self.path)

    def test_duplicate_id_returns_original_sid_and_never_redials(self):
        self.assertEqual(self.dial("first"), CALL)
        self.assertEqual(self.dial("first"), CALL)
        self.client.calls.create.assert_called_once_with(
            to=SETTINGS.allowed_phone_number, from_=SETTINGS.phone_number,
            url=SETTINGS.url("/api/telephony/voice"), method="POST",
            status_callback=SETTINGS.url("/api/telephony/call-status"),
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            time_limit=600, timeout=30, record=False,
        )

    def test_active_call_blocks_distinct_request_until_terminal(self):
        self.dial("first")
        self.client.calls.return_value.fetch.return_value = SimpleNamespace(status="ringing")
        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.dial("second")
        self.assertEqual(self.client.calls.create.call_count, 1)
        self.client.calls.return_value.fetch.return_value = SimpleNamespace(status="completed")
        self.dial("second")
        self.assertEqual(self.client.calls.create.call_count, 2)

    def test_ambiguous_timeout_is_persisted_and_blocks_all_automatic_redial(self):
        self.client.calls.create.side_effect = TimeoutError()
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            self.dial("first")
        for request_id in ["first", "second"]:
            with self.assertRaises(RuntimeError):
                self.dial(request_id)
        self.assertEqual(self.client.calls.create.call_count, 1)
        reconcile(SETTINGS, self.client, "first", self.path, no_call_created=True)
        self.client.calls.create.side_effect = None
        self.dial("second")
        self.assertEqual(self.client.calls.create.call_count, 2)

    def test_console_reconciliation_validates_configured_call_parties(self):
        self.client.calls.create.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError):
            self.dial("first")
        self.client.calls.return_value.fetch.return_value = SimpleNamespace(
            to="+12345678901", from_=SETTINGS.phone_number,
        )
        with self.assertRaises(ValueError):
            reconcile(SETTINGS, self.client, "first", self.path, call_sid=CALL)
        self.client.calls.return_value.fetch.return_value.to = SETTINGS.allowed_phone_number
        reconcile(SETTINGS, self.client, "first", self.path, call_sid=CALL)
        self.assertEqual(self.dial("first"), CALL)
        self.assertEqual(self.client.calls.create.call_count, 1)

    def test_definite_api_rejection_is_sanitized_and_does_not_block_new_id(self):
        self.client.calls.create.side_effect = TwilioRestException(
            403, "private-uri", msg="private-provider-details", code=21219,
        )
        with self.assertRaisesRegex(RuntimeError, "rejected") as caught:
            self.dial("first")
        self.assertNotIn("private", str(caught.exception))
        self.client.calls.create.side_effect = None
        self.dial("second")


if __name__ == "__main__":
    unittest.main()
