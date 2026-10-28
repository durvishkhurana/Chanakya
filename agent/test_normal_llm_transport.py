"""Prove native SDK tool-call streaming and trace export without provider requests."""

import json
import unittest

import httpx

from agent.models import OpenRouterChatOpenAI
from agent.normal_llm import NormalLLMAgent
from agent.test_batch_pageindex import batch_store, paths_for, selection_for
from agent.test_tracing import capture_traces, named


class LunaTransportFixture:
    def __init__(self):
        self.requests = []
        self.store = batch_store()
        self.http = httpx.Client(transport=httpx.MockTransport(self.respond))
        self.ahttp = httpx.AsyncClient(transport=httpx.MockTransport(self.respond))
        model = OpenRouterChatOpenAI(
            model="openai/gpt-6-luna", api_key="luna-test-secret",
            base_url="https://openrouter.ai/api/v1", reasoning_effort="none",
            streaming=True, stream_usage=True, max_retries=0,
            http_client=self.http, http_async_client=self.ahttp,
        )
        self.agent = NormalLLMAgent(self.store, model=model)

    def respond(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        if len(self.requests) == 1:
            delta = {"tool_calls": [{
                "id": "batch-one", "index": 0, "type": "function",
                "function": {"name": "read_pageindex", "arguments": json.dumps(selection_for(paths_for(self.store)))},
            }]}
            finish = "tool_calls"
            deltas = [delta]
        else:
            deltas = [{"tool_calls": [{
                "id": "reply-one", "index": 0, "type": "function",
                "function": {"name": "reply", "arguments": '{"text":"Luna grounded '},
            }]}, {"tool_calls": [{
                "index": 0, "function": {"arguments": 'answer."}'},
            }]}]
            finish = "tool_calls"
        chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas] + [
            {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            {"choices": [], "usage": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220}},
        ]
        return httpx.Response(200, text="".join(
            f"data: {json.dumps(chunk)}\n\n" for chunk in chunks
        ) + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    def assertions(self, case, reply, result, events):
        case.assertEqual(reply.content, "Luna grounded answer.")
        case.assertEqual(len(result.evidence), 6)
        case.assertEqual(len(self.requests), 2)
        for index, body in enumerate(self.requests):
            case.assertEqual(body["model"], "openai/gpt-6-luna")
            case.assertEqual(body["reasoning_effort"], "none")
            if index == 0:
                case.assertEqual(body["tools"][0]["function"]["name"], "read_pageindex")
                case.assertEqual(body["tools"][1]["function"]["name"], "reply")
                case.assertEqual(body["tool_choice"], "required")
                properties = body["tools"][0]["function"]["parameters"]["properties"]
                case.assertEqual(set(properties), {"source_ids"})
                case.assertEqual(set(properties["source_ids"]["items"]["enum"]), set(self.agent.index.source_ids))
            else:
                case.assertEqual([tool["function"]["name"] for tool in body["tools"]], ["reply"])
                case.assertEqual(body["tool_choice"], {"type": "function", "function": {"name": "reply"}})
            case.assertTrue(all(tool["function"]["strict"] for tool in body["tools"]))
            case.assertFalse(body["parallel_tool_calls"])
        tool = next(m for m in self.requests[1]["messages"] if m["role"] == "tool")
        case.assertEqual(tool["tool_call_id"], "batch-one")
        case.assertEqual(len(json.loads(tool["content"])["sources"]), 6)
        case.assertEqual([e["content"] for e in events if e["type"] == "token"], ["Luna grounded ", "answer."])


class LunaTransportTests(unittest.TestCase):
    def test_sync_native_stream_and_parented_traces(self):
        fixture = LunaTransportFixture()
        try:
            events = []
            with capture_traces() as spans:
                reply, result = fixture.agent.run("Hostels, admissions, scholarships?", [], emit=events.append)
            fixture.assertions(self, reply, result, events)
            root = named(spans, "normal_llm_agent")[0]
            models = named(spans, "luna_agent")
            self.assertEqual(len(models), 2)
            self.assertEqual(len(named(spans, "read_pageindex")), 1)
            for span in spans.values():
                self.assertEqual(str(span["trace_id"]), str(root["id"]))
                self.assertIn("end_time", span)
            self.assertNotIn("luna-test-secret", json.dumps(spans, default=str))
        finally:
            fixture.http.close()


class LunaAsyncTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_native_stream_and_usage(self):
        fixture = LunaTransportFixture()
        try:
            events = []
            reply, result = await fixture.agent.arun("Hostels and scholarships?", [], emit=events.append)
            fixture.assertions(self, reply, result, events)
            self.assertEqual(reply.usage_metadata["total_tokens"], 220)
        finally:
            await fixture.agent.aclose()


if __name__ == "__main__":
    unittest.main()
