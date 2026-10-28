import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from agent.decisions import DecisionError, DecisionsClient
from agent.graph import Agent
from agent.retrieval import ACTION_QUESTION, Retriever
from agent.test_graph import RecordingModel
from agent.test_retrieval import answer, documents, read_first
from agent.test_tracing import capture_traces

QUESTIONS = {
    "action": ACTION_QUESTION,
    "next_read": {
        "type": "choice",
        "instructions": "Choose the most useful source, independently of action.",
        "criteria": {"fees": "Tuition and hostel fees.", "awards": "Scholarships."},
    },
}


def response_body():
    return {
        "model": "openai/gpt-6-luna-decisions",
        "answers": {
            "action": {"type": "choice", "choice": "read_more",
                       "confidence": 0.9, "probabilities": {"read_more": 0.95, "ready_to_answer": 0.05}},
            "next_read": {"type": "choice", "choice": "fees",
                          "confidence": 0.9, "probabilities": {"fees": 0.95, "awards": 0.05}},
        },
        "usage": {"input_tokens": 100, "output_tokens": 0, "cost": 0.00001},
    }


class DecisionsTests(unittest.TestCase):
    def test_openrouter_decisions_retrieve_sources_then_call_answer_model_once(self):
        requests = []
        script = iter([read_first, read_first, answer("ready_to_answer")])

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            result = next(script)
            if callable(result):
                result = result(body["state"], body["questions"])
            result["model"] = "openai/gpt-6-luna-decisions"
            return httpx.Response(200, json=result)

        client = DecisionsClient(api_key="test-key")
        client._sync = httpx.Client(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        model = RecordingModel()
        try:
            with patch("agent.graph.ChatOpenAI", return_value=model):
                agent = Agent("Decisions", retrieval_mode="decisions", retriever=Retriever(
                    documents(), client
                ))
            emitted = list(agent.stream("Hostel fees?", config={
                "configurable": {"thread_id": "decisions-handoff"},
            }))
            self.assertEqual(len(requests), 3)
            self.assertEqual(len(model.calls), 1)
            self.assertIn("Hostel fees are Rs. 50000.", model.calls[0][-1].content)
            self.assertEqual(emitted[-1]["full_content"], "Grounded answer.")
        finally:
            client.close()

    def test_real_http_contract_maps_shared_multilingual_state_and_named_answers(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=response_body())

        client = DecisionsClient(api_key="credential-must-not-appear")
        client._sync = httpx.Client(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        state = {"question": "ਹੋਸਟਲ ਦੀ ਫੀਸ?", "evidence": []}
        try:
            with capture_traces() as spans:
                result = client.decide(state, QUESTIONS, 2)
            self.assertEqual(len(requests), 1)
            self.assertEqual(str(requests[0].url), "https://openrouter.ai/api/alpha/decisions")
            payload = json.loads(requests[0].content)
            self.assertEqual(payload["model"], "openai/gpt-6-luna-decisions")
            self.assertEqual(payload["state"], state)
            self.assertEqual(payload["questions"], QUESTIONS)
            self.assertEqual(payload["questions"]["next_read"]["criteria"]["fees"], "Tuition and hostel fees.")
            self.assertEqual(result["answers"]["next_read"]["choice"], "fees")
            span = next(s for s in spans.values() if s["name"] == "openai_decision")
            self.assertEqual(span["extra"]["metadata"]["ls_provider"], "openrouter")
            self.assertEqual(span["outputs"]["usage_metadata"]["output_tokens"], 0)
            self.assertNotIn(client.api_key, json.dumps(spans, default=str))
        finally:
            client.close()

    def test_http_failure_is_sanitized_and_not_retried(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(429, json={"error": "sensitive upstream body"})

        client = DecisionsClient(api_key="test-key")
        client._sync = httpx.Client(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        try:
            with self.assertRaisesRegex(DecisionError, "^OpenAI Decisions request failed$"):
                client.decide({}, QUESTIONS, 1)
            self.assertEqual(len(requests), 1)
        finally:
            client.close()

    def test_missing_openrouter_key_does_not_use_direct_openai_credentials(self):
        with (
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "", "OPENAI_API_KEY": "other"}),
            self.assertRaisesRegex(DecisionError, "Missing OPENROUTER_API_KEY"),
        ):
            DecisionsClient().decide({}, QUESTIONS, 1)

    def test_malformed_answers_are_rejected_and_refusals_are_preserved(self):
        for answers in ([], {}, {"unexpected": {"type": "choice"}}, [None]):
            with self.subTest(answers=answers), self.assertRaises((KeyError, TypeError, ValueError)):
                DecisionsClient._response(httpx.Response(
                    200, json={"answers": answers}, request=httpx.Request("POST", "https://example.test")
                ), QUESTIONS)
        body = response_body()
        body["answers"]["action"] = {"type": "refusal"}
        result = DecisionsClient._response(httpx.Response(
            200, json=body, request=httpx.Request("POST", "https://example.test")
        ), QUESTIONS)
        self.assertEqual(result["answers"]["action"]["type"], "refusal")


class AsyncDecisionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_failure_preserves_evidence_and_reports_incomplete_retrieval(self):
        script = iter([read_first, read_first, None])

        def respond(request):
            body = json.loads(request.content)
            result = next(script)
            if result is None:
                return httpx.Response(429, json={"error": "private upstream details"})
            return httpx.Response(200, json=result(body["state"], body["questions"]))

        client = DecisionsClient(api_key="test-key")
        client._async = httpx.AsyncClient(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        try:
            result = await Retriever(documents(), client).arun("Hostel fees?", [])
            self.assertEqual(result.stop_reason, "decision_error")
            self.assertEqual(result.evidence[0]["text"], "Hostel fees are Rs. 50000.")
            self.assertIn("evidence may be incomplete", result.limitation)
            self.assertNotIn("private upstream details", result.limitation)
        finally:
            await client.aclose()

    async def test_async_request_and_cleanup(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=response_body())

        client = DecisionsClient(api_key="test-key")
        transport = httpx.AsyncClient(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        client._async = transport
        result = await client.adecide({}, QUESTIONS, 1)
        self.assertEqual(result["answers"]["action"]["choice"], "read_more")
        self.assertEqual(len(requests), 1)
        await client.aclose()
        self.assertTrue(transport.is_closed)
        self.assertIsNone(client._async)

    async def test_cancellation_propagates(self):
        started = asyncio.Event()

        async def respond(request):
            started.set()
            await asyncio.Event().wait()

        client = DecisionsClient(api_key="test-key")
        client._async = httpx.AsyncClient(
            **client._options(), transport=httpx.MockTransport(respond)
        )
        task = asyncio.create_task(client.adecide({}, QUESTIONS, 1))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await client.aclose()
