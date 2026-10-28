"""Token budgeting must not download an unusable tokenizer on the response path."""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agent.graph import Agent
from agent.models import OpenRouterChatOpenAI


class OpenRouterTokenCountingTests(unittest.TestCase):
    def test_prefixed_model_uses_existing_estimate_without_loading_tokenizer(self):
        model = OpenRouterChatOpenAI(model="openai/gpt-4.1-mini", api_key="test")
        agent = object.__new__(Agent)
        agent.llm = model
        messages = [HumanMessage(content="Hello")]
        with patch.object(
            OpenRouterChatOpenAI, "_get_encoding_model",
            side_effect=RuntimeError("Unexpected tokenizer download"),
        ) as encoding:
            self.assertEqual(agent._message_tokens(messages), 7)
        encoding.assert_not_called()

    def test_explicit_tokenizer_model_keeps_langchain_counting(self):
        model = OpenRouterChatOpenAI(
            model="openai/gpt-4.1-mini", api_key="test",
            tiktoken_model_name="gpt-4.1-mini",
        )
        with patch(
            "langchain_openai.ChatOpenAI.get_num_tokens_from_messages", return_value=12,
        ) as count:
            self.assertEqual(model.get_num_tokens_from_messages([]), 12)
        count.assert_called_once_with([], tools=None)


if __name__ == "__main__":
    unittest.main()
