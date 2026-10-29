"""The voice agent follows the configured LLM provider without any network request."""

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from agent.graph import Agent
from agent.languages import spoken_text
from agent.models import OpenRouterChatOpenAI
from agent.normal_llm import NormalLLMAgent
from agent.prompts.prompts import voice_assistant_system_prompt
from agent.test_batch_pageindex import batch_store

GROQ = {"OPENROUTER_API_KEY": "", "GROQ_API_KEY": "groq-test-key", "LLM_PROVIDER": ""}
OPENROUTER = {"OPENROUTER_API_KEY": "router-test-key", "GROQ_API_KEY": "groq-test-key", "LLM_PROVIDER": ""}


class ProviderSelectionTests(unittest.TestCase):
    def test_openrouter_settings_are_unchanged_when_its_key_is_set(self):
        with patch.dict("os.environ", OPENROUTER):
            model = NormalLLMAgent(batch_store()).model
            agent = Agent(name="t", system_prompt=voice_assistant_system_prompt)
        self.assertEqual(model.model_name, "openai/gpt-6-luna")
        self.assertEqual(str(model.openai_api_base), "https://openrouter.ai/api/v1")
        self.assertEqual(model.service_tier, "fast")
        self.assertEqual(agent.model, "openai/gpt-4.1-mini")
        self.assertEqual(agent.llm.ls_provider_name, "openrouter")

    def test_groq_is_used_while_only_its_key_is_set(self):
        with patch.dict("os.environ", GROQ):
            model = NormalLLMAgent(batch_store()).model
            agent = Agent(name="t", system_prompt=voice_assistant_system_prompt)
        self.assertEqual(str(model.openai_api_base), "https://api.groq.com/openai/v1")
        self.assertEqual(model.model_name, "openai/gpt-oss-120b")
        self.assertIsNone(model.service_tier)
        self.assertEqual(model.openai_api_key.get_secret_value(), "groq-test-key")
        self.assertEqual(agent.model, "openai/gpt-oss-120b")
        self.assertEqual(agent.llm.ls_provider_name, "groq")
        self.assertEqual(agent._model_config()["metadata"]["ls_provider"], "groq")

    def test_explicit_provider_wins_over_key_detection(self):
        with patch.dict("os.environ", {**OPENROUTER, "LLM_PROVIDER": "groq"}):
            model = NormalLLMAgent(batch_store()).model
        self.assertEqual(model.model_name, "openai/gpt-oss-120b")


def plain_text_stream(request):
    chunks = [{"choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}]}
              for part in ("Hello — I am ", "Chanakya, an AI assistant.")]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


class GroqPlainTextTests(unittest.TestCase):
    def test_groq_plain_text_reply_is_spoken_once_without_em_dash(self):
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return plain_text_stream(request)

        model = OpenRouterChatOpenAI(
            model="openai/gpt-oss-120b", api_key="groq-test-key", base_url="https://api.groq.com/openai/v1",
            ls_provider_name="groq", streaming=True, max_retries=0,
            http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        agent = NormalLLMAgent(batch_store(), model=model)
        events = []
        reply, result = asyncio.run(agent.arun("Hello", [], emit=events.append))
        self.assertEqual(reply.content, "Hello, I am Chanakya, an AI assistant.")
        self.assertEqual([e["content"] for e in events if e["type"] == "token"], [reply.content])
        self.assertEqual(result.stop_reason, "answered")
        self.assertEqual(requests[0]["tool_choice"], "auto")

    def test_spoken_text_never_contains_an_em_dash(self):
        self.assertEqual(spoken_text("QR — or Soundbox—both"), "QR, or Soundbox, both")


if __name__ == "__main__":
    unittest.main()
