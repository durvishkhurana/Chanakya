import asyncio
import json
import unittest
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from agent.decisions import DecisionsClient
from agent.graph import Agent, AgentState
from agent.jev import JevClient
from agent.retrieval import Retriever
from agent.test_retrieval import ScriptedClient, answer, documents, read_first


class RecordingModel(BaseChatModel):
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "recording-model"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="Grounded answer."))]
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        for token in ("Grounded ", "answer."):
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self._stream(messages, stop, run_manager, **kwargs):
            yield chunk


def make_agent(script, **kwargs):
    client = ScriptedClient(script)
    model = RecordingModel()
    with patch("agent.graph.ChatOpenAI", return_value=model):
        agent = Agent(
            "Test",
            retrieval_mode="jev",
            retriever=Retriever(documents(), client, provider="jev"),
            **kwargs,
        )
    return agent, client, model


class GraphTests(unittest.TestCase):
    def test_decisions_is_default_and_jev_remains_available(self):
        with patch.dict("os.environ", {}, clear=True), patch(
            "agent.graph.ChatOpenAI", return_value=RecordingModel()
        ):
            agent = Agent("Default")
        self.assertIsInstance(agent.retriever.client, DecisionsClient)
        self.assertIsInstance(agent.retrievers["jev"].client, JevClient)
        self.assertIs(agent.retriever.store, agent.retrievers["jev"].store)

    def test_provider_switch_preserves_thread_history_and_resets_evidence(self):
        agent, jev, model = make_agent([read_first, read_first, answer("ready_to_answer")])
        decisions = ScriptedClient([answer("ready_to_answer")])
        agent.retrievers["decisions"] = Retriever(documents(), decisions)
        config = {"configurable": {"thread_id": "switch", "retrieval_provider": "jev"}}
        list(agent.stream("Hostel fees?", config=config))
        config["configurable"]["retrieval_provider"] = "decisions"
        list(agent.stream("And scholarships?", config=config))
        self.assertEqual(len(jev.calls), 3)
        self.assertEqual(len(decisions.calls), 1)
        state = decisions.calls[0][0]
        self.assertEqual(state["evidence"], [])
        self.assertTrue(any(m["text"] == "Hostel fees?" for m in state["conversation"]))
        self.assertTrue(any(m["text"] == "Grounded answer." for m in state["conversation"]))
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(agent.retrieval_mode, "jev")

    def test_invalid_provider_is_rejected(self):
        agent, _, _ = make_agent([])
        with self.assertRaisesRegex(ValueError, "Unknown retrieval provider"):
            agent._retriever_for({"configurable": {"retrieval_provider": "invented"}})

    def test_language_control_applies_in_both_modes_without_changing_chat_prompt(self):
        agent, _, _ = make_agent([])
        state = AgentState(messages=[HumanMessage(content="Yes")])
        for mode in ("jev", "llm"):
            agent.retrieval_mode = mode
            for language, name in (("pa-IN", "Punjabi"), ("en-IN", "English"), ("hi-IN", "Hindi")):
                messages = agent._answer_messages(state, {"configurable": {"response_language": language}})
                self.assertIn(f"respond in {name} ({language})", messages[0].content)
            self.assertEqual(agent._answer_messages(state)[0].content, agent.system_prompt)
            self.assertEqual(
                agent._answer_messages(state, {"configurable": {"response_language": "invented"}})[0].content,
                agent.system_prompt,
            )

    def test_long_conversation_retains_a_full_bounded_suffix(self):
        previous = "a" * 2000 + "₹" * 600 + " important follow-up detail"
        state = AgentState(
            messages=[
                HumanMessage(content=previous),
                HumanMessage(content="And hostel?"),
            ]
        )
        question, conversation = Agent._retrieval_input(state)
        self.assertEqual(question, "And hostel?")
        self.assertTrue(conversation[0]["text"].endswith("important follow-up detail"))
        self.assertGreater(len(conversation[0]["text"].encode("utf-8")), 1990)
        self.assertLessEqual(len(conversation[0]["text"].encode("utf-8")), 2000)
        self.assertTrue(conversation[0]["truncated"])

    def test_llm_called_once_after_source_retrieval_and_receives_full_evidence(self):
        agent, client, model = make_agent(
            [read_first, read_first, answer("ready_to_answer")]
        )
        events = list(
            agent.stream(
                "Hostel fees?", config={"configurable": {"thread_id": "chat-1"}}
            )
        )
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(len(client.calls), 3)
        prompt = model.calls[0][-1].content
        context = json.loads(prompt.split("\n", 1)[1])
        self.assertEqual(context["sources"][0]["text"], "Hostel fees are Rs. 50000.")
        self.assertEqual(context["sources"][0]["document"], "fees")
        self.assertEqual(context["stop_reason"], "ready_to_answer")
        self.assertEqual(events[-1]["full_content"], "Grounded answer.")
        self.assertEqual(
            len([event for event in events if event["type"] == "tool_call"]), 2
        )
        self.assertEqual(
            [event["content"] for event in events if event["type"] == "token"],
            ["Grounded ", "answer."],
        )

    def test_followup_keeps_conversation_but_resets_retrieval(self):
        agent, client, model = make_agent(
            [answer("ready_to_answer"), answer("ready_to_answer")]
        )
        config = {"configurable": {"thread_id": "followup"}}
        agent.invoke("B.Tech fees?", config=config)
        agent.invoke("And hostel?", config=config)
        previous = client.calls[1][0]["conversation"]
        self.assertEqual(previous[0]["text"], "B.Tech fees?")
        self.assertEqual(previous[1]["role"], "assistant")
        self.assertEqual(client.calls[1][0]["evidence"], [])
        self.assertEqual(client.calls[1][0]["history"], [])
        self.assertEqual(len(model.calls), 2)

    def test_threads_do_not_share_history(self):
        agent, client, _model = make_agent(
            [answer("ready_to_answer"), answer("ready_to_answer")]
        )
        agent.invoke(
            "Private question", config={"configurable": {"thread_id": "first"}}
        )
        agent.invoke("Other question", config={"configurable": {"thread_id": "second"}})
        self.assertEqual(client.calls[1][0]["conversation"], [])

    def test_running_summary_carries_older_user_fact_to_jev_and_answer(self):
        agent, client, model = make_agent(
            [answer("ready_to_answer")] * 3,
            summary_history_budget_chars=1,
            summary_max_chars=100,
            recent_message_count=3,
        )
        summarized = []

        def summarize(summary, messages):
            summarized.extend(Agent._summary_input(messages))
            return "User stated their preferred name is Chanakya."

        agent._summarize = summarize
        config = {"configurable": {"thread_id": "summary-facts"}}
        agent.invoke("My preferred name is Chanakya.", config=config)
        agent.invoke("Please use that name.", config=config)
        agent.invoke("What name did I give you?", config=config)

        jev_conversation = client.calls[2][0]["conversation"]
        memory = next(item for item in jev_conversation if item["role"] == "summary")
        self.assertIn("Chanakya", memory["text"])
        self.assertEqual(jev_conversation[-2]["text"], "Please use that name.")
        self.assertEqual(jev_conversation[-1]["role"], "assistant")
        self.assertEqual(summarized[0]["role"], "user")
        self.assertIn("My preferred name is Chanakya.", summarized[0]["text"])
        self.assertTrue(any("User stated their preferred name is Chanakya." in item.content
                            for item in model.calls[-1]))

    def test_summary_is_thread_isolated_and_failure_keeps_cursor(self):
        agent, client, _model = make_agent(
            [answer("ready_to_answer")] * 4,
            summary_history_budget_chars=1,
            recent_message_count=1,
        )
        config_a = {"configurable": {"thread_id": "summary-a"}}
        config_b = {"configurable": {"thread_id": "summary-b"}}
        agent._summarize = lambda _summary, _messages: "User said secret: orchid."
        agent.invoke("Remember orchid.", config=config_a)
        agent.invoke("Follow up A", config=config_a)
        self.assertIn("orchid", json.dumps(client.calls[1][0]["conversation"]))

        agent._summarize = lambda *_args: (_ for _ in ()).throw(RuntimeError("offline"))
        agent.invoke("Other thread", config=config_b)
        failed = agent.invoke("Follow up B", config=config_b)
        state_b = agent.runnable.get_state(config_b).values
        self.assertEqual(state_b.get("conversation_summary", ""), "")
        self.assertEqual(state_b.get("summary_cursor", 0), 0)
        self.assertNotIn("orchid", json.dumps(client.calls[-1][0]["conversation"]))

        state_a = agent.runnable.get_state(config_a).values
        self.assertIn("orchid", state_a["conversation_summary"])
        self.assertTrue(failed["messages"][-1].content)

    def test_answer_budget_keeps_current_question_and_reserves_response_space(self):
        agent, _, _model = make_agent(
            [],
            system_prompt="Answer briefly.",
            answer_context_budget_tokens=200,
            answer_response_reserve_tokens=40,
        )
        agent.retrieval_mode = "llm"
        from langchain_core.messages import AIMessage

        messages = [
            HumanMessage(content=f"old turn {index} " + "detail " * 25)
            if index % 2 == 0
            else AIMessage(content=f"old answer {index} " + "detail " * 25)
            for index in range(10)
        ] + [HumanMessage(content="Keep this exact current question?")]
        fitted = agent._fit_answer_messages(messages)
        self.assertLessEqual(
            agent._message_tokens(fitted),
            agent.answer_context_budget_tokens - agent.answer_response_reserve_tokens,
        )
        self.assertEqual(fitted[-1].content, "Keep this exact current question?")

    def test_answer_budget_counts_prompt_and_retrieval_evidence(self):
        agent, _, _model = make_agent(
            [],
            system_prompt="Use the evidence precisely.",
            answer_context_budget_tokens=600,
            answer_response_reserve_tokens=100,
        )
        evidence = "A retrieved fact. " * 500
        state = AgentState(
            messages=[HumanMessage(content="Keep this question exactly?")],
            retrieval={
                "evidence": [{"document": "facts", "text": evidence}],
                "history": [],
                "stop_reason": "ready_to_answer",
                "limitation": "",
            },
        )
        fitted = agent._answer_messages(state)
        self.assertLessEqual(agent._message_tokens(fitted), 500)
        self.assertTrue(any(message.content == "Keep this question exactly?" for message in fitted))
        context_message = next(
            message
            for message in fitted
            if message.content.startswith("The following JSON is application-supplied")
        )
        context = json.loads(context_message.content.split("\n", 1)[1])
        self.assertLess(len(context["sources"][0]["text"]), len(evidence))

    def test_forced_stop_is_transferred_as_a_limitation(self):
        agent, _client, model = make_agent([answer("read_more", "invalid")])
        agent.invoke("fees", config={"configurable": {"thread_id": "limited"}})
        context = json.loads(model.calls[0][-1].content.split("\n", 1)[1])
        self.assertEqual(context["stop_reason"], "invalid_decision")
        self.assertTrue(context["limitation"])
        self.assertEqual(context["sources"], [])


class AsyncGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_finished_phone_checkpoint_cleanup_preserves_browser_conversation(self):
        agent, _client, _model = make_agent([answer("ready_to_answer"), answer("ready_to_answer")])
        phone = {"configurable": {"thread_id": "phone:finished"}}
        browser = {"configurable": {"thread_id": "browser:ongoing"}}
        for config in [phone, browser]:
            async for _event in agent.astream("Hello", config=config):
                pass
        saver = agent.runnable.checkpointer
        self.assertIsNotNone(await saver.aget_tuple(phone))
        self.assertIsNotNone(await saver.aget_tuple(browser))
        await agent.forget_thread("phone:finished")
        self.assertIsNone(await saver.aget_tuple(phone))
        self.assertIsNotNone(await saver.aget_tuple(browser))

    async def test_concurrent_requests_keep_provider_selection_separate(self):
        agent, jev, model = make_agent([read_first, read_first, answer("ready_to_answer")])
        decisions = ScriptedClient([answer("ready_to_answer")])
        agent.retrievers["decisions"] = Retriever(documents(), decisions)

        async def collect(provider, question):
            return [event async for event in agent.astream(question, config={
                "configurable": {"thread_id": provider, "retrieval_provider": provider},
            })]

        jev_events, decision_events = await asyncio.gather(
            collect("jev", "Hostel fees?"), collect("decisions", "Hello")
        )
        self.assertEqual(jev.calls[0][0]["question"], "Hostel fees?")
        self.assertEqual(decisions.calls[0][0]["question"], "Hello")
        self.assertEqual(len(jev.calls), 3)
        self.assertEqual(len(decisions.calls), 1)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(jev_events[-1]["type"], "done")
        self.assertEqual(decision_events[-1]["type"], "done")

    async def test_voice_language_reaches_answer_after_english_evidence(self):
        agent, _, model = make_agent([read_first, read_first, answer("ready_to_answer")])
        async for _ in agent.astream("ਹੋਸਟਲ ਦੀ ਫੀਸ ਕਿੰਨੀ ਹੈ?", config={"configurable": {
            "thread_id": "punjabi", "response_language": "pa-IN",
        }}):
            pass
        self.assertIn("respond in Punjabi (pa-IN)", model.calls[0][0].content)
        self.assertIn("Hostel fees are Rs. 50000.", model.calls[0][-1].content)

    async def test_voice_uses_same_handoff_and_streams_only_final_answer(self):
        agent, client, model = make_agent(
            [read_first, read_first, answer("ready_to_answer")],
            system_prompt="Speak briefly.",
        )
        events = [
            event
            async for event in agent.astream(
                "Hostel fees?", config={"configurable": {"thread_id": "voice"}}
            )
        ]
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0][0].content, "Speak briefly.")
        self.assertEqual(events[-1]["full_content"], "Grounded answer.")

    async def test_voice_cancellation_never_calls_answer_model(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        class WaitingClient:
            async def adecide(self, *_args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        agent, _client, model = make_agent([])
        agent.retriever.client = WaitingClient()

        async def consume():
            async for _event in agent.astream(
                "fees", config={"configurable": {"thread_id": "cancel"}}
            ):
                pass

        task = asyncio.create_task(consume())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())
        self.assertEqual(model.calls, [])
