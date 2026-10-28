import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.voice_interruption import (
    ACTION_QUESTION,
    MAX_REQUEST_BYTES,
    VoiceInterruptionClassifier,
    _trace_summary,
)


def result(choice="take_turn", **fields):
    return {"answers": {"action": {"type": "choice", "choice": choice, **fields}}}


class VoiceInterruptionTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, response=None, side_effect=None):
        client = AsyncMock()
        client.adecide = AsyncMock(return_value=response, side_effect=side_effect)
        client.aclose = AsyncMock()
        return client

    def test_trace_summary_adds_thread_metadata_without_transcript_or_credentials(self):
        run = SimpleNamespace(metadata={})
        inputs = {
            "text": "caller transcript must not be logged",
            "context": {
                "thread_id": "conversation-123",
                "overlap": True,
                "last_user_text": "private earlier transcript",
            },
            "language": "en-IN",
            "response_id": 2,
            "utterance_id": 3,
            "api_key": "secret-api-key",
        }

        with patch("backend.voice_interruption.get_current_run_tree", return_value=run):
            summary = _trace_summary(inputs)

        self.assertEqual(summary["thread_id"], "conversation-123")
        self.assertEqual(run.metadata, {"thread_id": "conversation-123"})
        self.assertNotIn("caller transcript must not be logged", str(summary))
        self.assertNotIn("private earlier transcript", str(summary))
        self.assertNotIn("secret-api-key", str(summary))

    async def test_submits_one_typed_decision_with_complete_utterance_and_context(self):
        client = self.make_client(result("take_turn", confidence=0.72, probabilities={"take_turn": 0.72}))
        classifier = VoiceInterruptionClassifier(client=client)
        text = "okay, but does that include electricity?"
        context = {
            "assistant_text": "Hostel fees are billed each semester.",
            "last_user_text": "What do hostel fees cover?",
            "recent_history": [{"role": "assistant", "text": "Let's review the fees."}],
            "overlap": True,
            "answer_requested": True,
        }

        decision = await classifier.classify(
            text, context, language="en-IN", response_id=4, utterance_id=8
        )

        client.adecide.assert_awaited_once()
        state, questions, timeout = client.adecide.await_args.args
        self.assertEqual(state["utterance"], text)
        self.assertEqual(state["assistant_text_generated"], context["assistant_text"])
        self.assertEqual(state["recent_history"][0]["text"], context["recent_history"][0]["text"])
        self.assertEqual(state["last_user_text"], context["last_user_text"])
        self.assertEqual((state["overlap"], state["response_id"], state["utterance_id"]), (True, 4, 8))
        self.assertEqual(questions, {"action": ACTION_QUESTION})
        self.assertEqual(timeout, 4.0)
        self.assertEqual(decision.choice, "take_turn")
        self.assertEqual(decision.confidence, 0.72)
        self.assertEqual(decision.probabilities, {"take_turn": 0.72})
        self.assertTrue(decision.takes_turn)
        await classifier.aclose()
        client.aclose.assert_not_awaited()

    async def test_acknowledgment_is_only_choice_that_does_not_take_turn(self):
        for choice, takes_turn in (("acknowledgment", False), ("uncertain", True), ("take_turn", True)):
            classifier = VoiceInterruptionClassifier(client=self.make_client(result(choice)))
            decision = await classifier.classify("okay", {"overlap": True})
            self.assertEqual(decision.choice, choice)
            self.assertEqual(decision.takes_turn, takes_turn)

    async def test_short_answers_are_sent_and_not_filtered_by_text(self):
        for phrase in ("no", "what?", "yes", "okay"):
            client = self.make_client(result("take_turn"))
            decision = await VoiceInterruptionClassifier(client=client).classify(
                phrase, {"overlap": True}
            )
            client.adecide.assert_awaited_once()
            self.assertIsNone(client.adecide.await_args.args[0]["answer_requested"])
            self.assertEqual(decision.choice, "take_turn")

    async def test_acknowledgment_cannot_swallow_answer_to_assistant_question(self):
        client = self.make_client(result("acknowledgment", confidence=0.97))
        classifier = VoiceInterruptionClassifier(client=client)

        decision = await classifier.classify(
            "okay",
            {
                "assistant_text": "Would you like me to compare CSE and ECE?",
                "answer_requested": True,
                "overlap": True,
            },
        )

        client.adecide.assert_awaited_once()
        request_state = client.adecide.await_args.args[0]
        self.assertTrue(request_state["answer_requested"])
        self.assertEqual(decision.choice, "uncertain")
        self.assertEqual(decision.fallback_reason, "answer_requested")
        self.assertEqual(decision.confidence, 0.97)
        self.assertTrue(decision.takes_turn)

    async def test_malformed_or_disallowed_output_falls_back_to_take_turn(self):
        for response in (
            {},
            {"answers": {"action": {"type": "text", "choice": "acknowledgment"}}},
            result("ignore"),
            {"answers": {"action": None}},
        ):
            with self.subTest(response=response):
                decision = await VoiceInterruptionClassifier(
                    client=self.make_client(response)
                ).classify("okay", {"overlap": True})
                self.assertEqual((decision.choice, decision.fallback_reason), ("take_turn", "invalid_output"))

    async def test_timeout_and_provider_errors_use_bounded_fallback(self):
        async def slow(*_args):
            await asyncio.sleep(0.05)

        for effect, timeout, expected in (
            (slow, 0.005, "timeout"),
            (RuntimeError("Missing TYPESAFE_API_KEY"), 0.1, "missing_credentials"),
            (OSError("provider offline"), 0.1, "request_error"),
        ):
            decision = await VoiceInterruptionClassifier(
                client=self.make_client(side_effect=effect), timeout=timeout
            ).classify("no", {"overlap": True})
            self.assertEqual((decision.choice, decision.fallback_reason), ("take_turn", expected))

    async def test_invalid_oversized_or_empty_request_fails_open_without_call(self):
        client = self.make_client(result("acknowledgment"))
        classifier = VoiceInterruptionClassifier(client=client)
        cases = (("", {}, "empty_utterance"), ("x" * 2001, {}, "utterance_too_large"))
        for text, context, reason in cases:
            decision = await classifier.classify(text, context)
            self.assertEqual((decision.choice, decision.fallback_reason), ("take_turn", reason))
        client.adecide.assert_not_awaited()
        self.assertGreater(MAX_REQUEST_BYTES, 0)

    async def test_cancellation_propagates_without_becoming_fallback(self):
        client = self.make_client(side_effect=asyncio.CancelledError())
        classifier = VoiceInterruptionClassifier(client=client)
        with self.assertRaises(asyncio.CancelledError):
            await classifier.classify("wait", {"overlap": True})

    async def test_owned_client_is_closed_once_and_injected_client_is_not(self):
        owned = self.make_client()
        with patch("backend.voice_interruption.JevClient", return_value=owned) as factory:
            classifier = VoiceInterruptionClassifier()
        factory.assert_called_once_with(purpose="voice_interruption")
        await classifier.aclose()
        await classifier.aclose()
        owned.aclose.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
