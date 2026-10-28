"""Exercise real SDK HTTP calls and exported LangSmith spans without API keys."""

import asyncio
import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import httpx2
from langsmith import Client, tracing_context
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient

from agent.graph import Agent
from agent.jev import JevClient, _trace_outputs
from agent.models import OpenRouterChatOpenAI
from agent.retrieval import Retriever
from agent.test_retrieval import answer, documents, read_first
from agent.tools import get_node_text


@contextmanager
def capture_traces():
    client = Client(api_key="trace-test-key", auto_batch_tracing=False)
    spans = {}

    def create(**kwargs):
        spans[str(kwargs["id"])] = copy.deepcopy(kwargs)

    def update(run_id, **kwargs):
        # Null update fields leave values from create_run unchanged on the server.
        spans[str(run_id)].update(
            copy.deepcopy(
                {key: value for key, value in kwargs.items() if value is not None}
            )
        )

    try:
        with (
            patch.object(Client, "create_run", side_effect=create),
            patch.object(Client, "update_run", side_effect=update),
            tracing_context(enabled=True, client=client),
        ):
            yield spans
    finally:
        client.close()


class HTTPFixture:
    def __init__(self, script=None, fail_llm=False):
        self.script = list(
            script
            if script is not None
            else [read_first, read_first, answer("ready_to_answer")]
        )
        self.jev_requests = []
        self.llm_requests = []
        self.fail_llm = fail_llm
        self.llm_tool = False
        self.jev = JevClient(api_key="jev-credential-must-not-appear")
        options = {
            "api_key": self.jev.api_key,
            "retry": RetryPolicy(max_retries=0),
            "transport": httpx2.MockTransport(self.respond_jev),
        }
        self.jev._sync = TypeSafeClient(**options)
        self.jev._async = AsyncTypeSafeClient(**options)
        self.http = httpx.Client(transport=httpx.MockTransport(self.respond_llm))
        self.ahttp = httpx.AsyncClient(transport=httpx.MockTransport(self.respond_llm))
        self.model = OpenRouterChatOpenAI(
            api_key="llm-credential-must-not-appear",
            model="openai/gpt-4.1-mini",
            base_url="https://openrouter.ai/api/v1",
            streaming=True,
            stream_usage=True,
            http_client=self.http,
            http_async_client=self.ahttp,
            max_retries=0,
        )
        with patch("agent.graph.ChatOpenAI", return_value=self.model):
            self.agent = Agent(
                "Chanakya",
                retrieval_mode="jev",
                retriever=Retriever(documents(), self.jev, provider="jev"),
            )

    def respond_jev(self, request):
        body = json.loads(request.content)
        self.jev_requests.append(body)
        decision = self.script.pop(0)
        if isinstance(decision, Exception):
            raise decision
        if callable(decision):
            decision = decision(body["state"], body["questions"])
        decision = copy.deepcopy(decision)
        if decision["answers"]["next_read"]["choice"] is None:
            # The SDK requires a choice even when readiness makes it unused.
            target = next(iter(body["questions"]["next_read"]["criteria"]))
            decision["answers"]["next_read"].update(
                choice=target, probabilities={target: 1.0}
            )
        return httpx2.Response(200, json=decision)

    def respond_llm(self, request):
        self.llm_requests.append(json.loads(request.content))
        if self.fail_llm:
            return httpx.Response(400, json={"error": {"message": "mock failure"}})
        chunks = [
            {
                "id": "test-completion",
                "model": "openai/gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": "Grounded "},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "test-completion",
                "model": "openai/gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "answer."},
                        "finish_reason": "stop",
                    }
                ],
            },
            {
                "id": "test-completion",
                "model": "openai/gpt-4.1-mini",
                "choices": [],
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 20,
                    "total_tokens": 220,
                },
            },
        ]
        if self.llm_tool and len(self.llm_requests) == 1:
            chunks[0]["choices"][0]["delta"] = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "read-fees",
                        "type": "function",
                        "function": {
                            "name": "get_node_text",
                            "arguments": json.dumps(
                                {"doc_name": "fees", "node_id": "0000"}
                            ),
                        },
                    }
                ],
            }
            chunks[1]["choices"][0].update(delta={}, finish_reason="tool_calls")
        sse = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        return httpx.Response(
            200,
            text=sse + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    async def aclose(self):
        await self.jev.aclose()
        self.http.close()
        await self.ahttp.aclose()


def named(spans, name):
    return [span for span in spans.values() if span["name"] == name]


class TraceAssertions:
    def assert_pipeline(self, fixture, spans, root_name="Chanakya"):
        roots = [s for s in spans.values() if s.get("parent_run_id") is None]
        self.assertEqual(len(roots), 1)
        root = roots[0]
        self.assertEqual(root["name"], root_name)
        for span in spans.values():
            self.assertEqual(str(span["trace_id"]), str(root["id"]))
            self.assertIn("end_time", span)
            if span.get("parent_run_id") is not None:
                self.assertIn(str(span["parent_run_id"]), spans)
        retrieval = named(spans, "source_retrieval")[0]
        self.assertEqual(retrieval["outputs"]["stop_reason"], "ready_to_answer")
        decisions = named(spans, "jev_decision")
        self.assertEqual(len(decisions), len(fixture.jev_requests))
        self.assertEqual(len(decisions), 3)
        for span in decisions:
            self.assertEqual(span["run_type"], "llm")
            self.assertEqual(str(span["parent_run_id"]), str(retrieval["id"]))
            self.assertEqual(set(span["inputs"]["questions"]), {"action", "next_read"})
            self.assertEqual(span["outputs"]["usage_metadata"]["total_tokens"], 110)
            self.assertIn("confidence", span["outputs"]["answers"]["action"])
            self.assertEqual(span["extra"]["metadata"]["ls_provider"], "typesafe")
            self.assertEqual(span["extra"]["metadata"]["ls_model_name"], "jev-1.13.0")
        tools = named(spans, "fetch_local_source")
        self.assertEqual(len(tools), 2)
        for span in tools:
            self.assertEqual(span["run_type"], "tool")
            self.assertEqual(str(span["parent_run_id"]), str(retrieval["id"]))
            self.assertEqual(span["extra"]["metadata"]["document"], "fees")
            self.assertNotIn("self", span["inputs"])
        self.assertEqual(tools[1]["outputs"]["text"], "Hostel fees are Rs. 50000.")
        llms = named(spans, "llm_answer")
        self.assertEqual(len(llms), len(fixture.llm_requests))
        self.assertEqual(len(llms), 1)
        llm = llms[0]
        self.assertEqual(llm["run_type"], "llm")
        self.assertEqual(llm["extra"]["metadata"]["ls_provider"], "openrouter")
        self.assertEqual(
            llm["extra"]["metadata"]["ls_model_name"], "openai/gpt-4.1-mini"
        )
        generation = llm["outputs"]["generations"][0][0]
        self.assertEqual(generation["text"], "Grounded answer.")
        self.assertEqual(
            generation["message"]["kwargs"]["usage_metadata"]["total_tokens"], 220
        )
        self.assertTrue(fixture.llm_requests[0]["stream_options"]["include_usage"])
        serialized = str(spans)
        for credential in (
            "jev-credential-must-not-appear",
            "llm-credential-must-not-appear",
            "trace-test-key",
        ):
            self.assertNotIn(credential, serialized)


class SyncTraceTests(TraceAssertions, unittest.TestCase):
    def test_legacy_mode_traces_each_llm_invocation_and_native_tool(self):
        fixture = HTTPFixture()
        fixture.llm_tool = True
        source = {
            "fees": {
                "tree": {
                    "result": [
                        {"node_id": "0000", "text": "Hostel fees are Rs. 50000."}
                    ]
                }
            }
        }
        try:
            with (
                patch("agent.graph.ChatOpenAI", return_value=fixture.model),
                patch("agent.graph.all_tools", [get_node_text]),
                patch("agent.tools._DOCS", source),
                capture_traces() as spans,
            ):
                agent = Agent("Chanakya", retrieval_mode="llm")
                events = list(
                    agent.stream(
                        "fees", config={"configurable": {"thread_id": "baseline"}}
                    )
                )
            models = named(spans, "llm_agent")
            self.assertEqual(len(models), 2)
            self.assertEqual(len(fixture.llm_requests), 2)
            self.assertEqual(fixture.jev_requests, [])
            tool = named(spans, "get_node_text")[0]
            self.assertEqual(tool["run_type"], "tool")
            self.assertEqual(tool["inputs"], {"doc_name": "fees", "node_id": "0000"})
            self.assertEqual(
                tool["outputs"]["output"].content, "Hostel fees are Rs. 50000."
            )
            root = named(spans, "Chanakya")[0]
            for span in spans.values():
                self.assertEqual(str(span["trace_id"]), str(root["id"]))
            self.assertEqual(events[-1]["full_content"], "Grounded answer.")
        finally:
            asyncio.run(fixture.aclose())

    def test_chat_stream_traces_real_sdk_calls_tools_and_usage(self):
        fixture = HTTPFixture()
        config = {
            "run_name": "custom-chat",
            "tags": ["request-tag"],
            "metadata": {"request_id": "r1"},
            "configurable": {"thread_id": "chat-session"},
        }
        original = copy.deepcopy(config)
        try:
            with capture_traces() as spans:
                events = list(fixture.agent.stream("Hostel fees?", config=config))
            self.assert_pipeline(fixture, spans, root_name="custom-chat")
            self.assertEqual(events[-1]["full_content"], "Grounded answer.")
            self.assertEqual(config, original)
            self.assertIn("request-tag", named(spans, "custom-chat")[0]["tags"])
            self.assertIn("request-tag", named(spans, "llm_answer")[0]["tags"])
            for span in spans.values():
                self.assertEqual(span["extra"]["metadata"]["thread_id"], "chat-session")
                self.assertEqual(span["extra"]["metadata"]["request_id"], "r1")
        finally:
            asyncio.run(fixture.aclose())

    def test_sync_invoke_also_traces_complete_pipeline(self):
        fixture = HTTPFixture()
        try:
            with capture_traces() as spans:
                result = fixture.agent.invoke(
                    "fees", config={"configurable": {"thread_id": "invoke"}}
                )
            self.assert_pipeline(fixture, spans)
            self.assertEqual(result["messages"][-1].content, "Grounded answer.")
        finally:
            asyncio.run(fixture.aclose())

    def test_jev_failure_is_visible_before_limited_answer(self):
        fixture = HTTPFixture(script=[RuntimeError("mock failure")])
        try:
            with capture_traces() as spans:
                fixture.agent.invoke(
                    "fees", config={"configurable": {"thread_id": "failed"}}
                )
            self.assertIn("mock failure", named(spans, "jev_decision")[0]["error"])
            self.assertEqual(
                named(spans, "source_retrieval")[0]["outputs"]["stop_reason"], "decision_error"
            )
            self.assertEqual(len(named(spans, "llm_answer")), 1)
            self.assertEqual(named(spans, "fetch_local_source"), [])
        finally:
            asyncio.run(fixture.aclose())

    def test_llm_http_failure_marks_model_and_root_as_failed(self):
        fixture = HTTPFixture(script=[answer("ready_to_answer")], fail_llm=True)
        try:
            with (
                capture_traces() as spans,
                self.assertRaisesRegex(Exception, "mock failure"),
            ):
                fixture.agent.invoke(
                    "fees", config={"configurable": {"thread_id": "llm-failed"}}
                )
            self.assertIn("mock failure", named(spans, "llm_answer")[0]["error"])
            self.assertIn("mock failure", named(spans, "Chanakya")[0]["error"])
            self.assertEqual(len(fixture.llm_requests), 1)
        finally:
            asyncio.run(fixture.aclose())

    def test_missing_usage_is_not_fabricated(self):
        response = answer("ready_to_answer")
        response["usage"] = None
        outputs = _trace_outputs(response)
        self.assertNotIn("usage_metadata", outputs)
        self.assertNotIn("choices", response)
        self.assertEqual(_trace_outputs(None), {})


class AsyncTraceTests(TraceAssertions, unittest.IsolatedAsyncioTestCase):
    async def test_voice_stream_preserves_one_trace_across_async_sdk_calls(self):
        fixture = HTTPFixture()
        fixture.agent.name = "Chanakya-Voice"
        try:
            with capture_traces() as spans:
                events = [
                    event
                    async for event in fixture.agent.astream(
                        "fees", config={"configurable": {"thread_id": "voice-session"}}
                    )
                ]
            self.assert_pipeline(fixture, spans, root_name="Chanakya-Voice")
            self.assertEqual(events[-1]["full_content"], "Grounded answer.")
            for span in spans.values():
                self.assertEqual(
                    span["extra"]["metadata"]["thread_id"], "voice-session"
                )
        finally:
            await fixture.aclose()

    async def test_cancellation_closes_jev_span_without_answer_call(self):
        fixture = HTTPFixture()
        started = asyncio.Event()

        async def waiting(_request):
            started.set()
            await asyncio.Event().wait()

        await fixture.jev._async.aclose()
        fixture.jev._async = AsyncTypeSafeClient(
            api_key="test-key",
            retry=RetryPolicy(max_retries=0),
            transport=httpx2.MockTransport(waiting),
        )

        async def consume():
            return [
                event
                async for event in fixture.agent.astream(
                    "fees", config={"configurable": {"thread_id": "cancelled"}}
                )
            ]

        try:
            with capture_traces() as spans:
                task = asyncio.create_task(consume())
                await asyncio.wait_for(started.wait(), timeout=2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            decision = named(spans, "jev_decision")[0]
            self.assertIn("CancelledError", decision["error"])
            self.assertIn("end_time", decision)
            self.assertEqual(named(spans, "llm_answer"), [])
            self.assertEqual(fixture.llm_requests, [])
        finally:
            await fixture.aclose()
