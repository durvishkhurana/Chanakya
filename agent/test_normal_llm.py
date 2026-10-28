import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessageChunk, ToolMessage

from agent.normal_llm import NormalLLMAgent
from agent.test_batch_pageindex import batch_store, paths_for, selection_for
from agent.test_graph import make_agent


def query(paths, content=""):
    return AIMessageChunk(content=content, tool_call_chunks=[{
        "name": "read_pageindex", "args": json.dumps(selection_for(paths)),
        "id": "read-batch", "index": 0,
    }])


def reply_chunk(arguments, *, first=False):
    return AIMessageChunk(content="", tool_call_chunks=[{
        "name": "reply" if first else None, "args": arguments,
        "id": "spoken-reply" if first else None, "index": 0,
    }])


def spoken_reply(text):
    return reply_chunk(json.dumps({"text": text}), first=True)


class ScriptedModel:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.root_client = Mock()
        self.root_async_client = Mock(close=unittest.mock.AsyncMock())

    def bind_tools(self, tools, **options):
        parent = self

        class Binding:
            def stream(self, messages, **kwargs):
                parent.calls.append((list(messages), options, tools))
                chunks = parent.script.pop(0)
                if isinstance(chunks, Exception):
                    raise chunks
                yield from chunks

            async def astream(self, messages, **kwargs):
                for chunk in self.stream(messages, **kwargs):
                    await asyncio.sleep(0)
                    yield chunk

        return Binding()


class NormalLLMTests(unittest.TestCase):
    def setUp(self):
        self.store = batch_store()
        self.paths = paths_for(self.store)

    def agent(self, script):
        model = ScriptedModel(script)
        return NormalLLMAgent(self.store, model=model), model

    def test_reply_reaches_speech_before_model_finishes(self):
        events = []

        def chunks():
            yield reply_chunk('{"text":"First sentence. ', first=True)
            self.assertEqual(events, [{"type": "token", "content": "First sentence. "}])
            yield reply_chunk('Second sentence."}')

        agent, model = self.agent([chunks()])
        message, result = agent.run("Hello", [], voice=True, emit=events.append)
        self.assertEqual(message.content, "First sentence. Second sentence.")
        self.assertFalse(message.tool_calls)
        self.assertFalse(result.evidence)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual([event["content"] for event in events], ["First sentence. ", "Second sentence."])

    def test_reply_decodes_split_unicode_and_escapes_without_duplicate_tokens(self):
        text = 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ। 😃 "quoted" \\ path\nNext line.'
        arguments = json.dumps({"text": text})
        agent, _model = self.agent([[reply_chunk(char, first=index == 0) for index, char in enumerate(arguments)]])
        events = []
        message, _result = agent.run("Hello", [], emit=events.append)
        self.assertEqual(message.content, text)
        self.assertEqual("".join(event["content"] for event in events), text)
        for event in events:
            event["content"].encode("utf-8")

    def test_preamble_is_never_spoken_even_when_it_precedes_tool_chunks(self):
        agent, _model = self.agent([
            [AIMessageChunk(content="Internal lookup t00003. "), query(self.paths)],
            [spoken_reply("Grounded reply.")],
        ])
        events = []
        agent.run("College facts?", [], emit=events.append)
        self.assertEqual([event["content"] for event in events if event["type"] == "token"], ["Grounded reply."])

    def test_incomplete_reply_arguments_do_not_finish_as_a_successful_answer(self):
        agent, _model = self.agent([[reply_chunk('{"text":"Unfinished.', first=True)]])
        with self.assertRaises(json.JSONDecodeError):
            agent.run("Hello", [])

    def test_greeting_uses_one_model_call_and_no_sources(self):
        agent, model = self.agent([[spoken_reply("Hello, I'm Chanakya.")]])
        events = []
        with patch.object(agent.index, "read", side_effect=AssertionError("Greeting queried sources")):
            reply, result = agent.run("Hello", [], emit=events.append)
        self.assertEqual(reply.content, "Hello, I'm Chanakya.")
        self.assertEqual(len(model.calls), 1)
        self.assertFalse(result.evidence)
        self.assertEqual(events, [{"type": "token", "content": reply.content}])

    def test_three_paths_are_read_in_one_call_then_same_model_answers(self):
        agent, model = self.agent([
            [query(self.paths, "Let me check internal IDs.")],
            [spoken_reply("According to the source, actual eligibility applies.")],
        ])
        events = []
        reply, result = agent.run("Compare admission, hostel and scholarship eligibility", [], emit=events.append)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(result.evidence), 6)
        self.assertEqual(len(result.history), 1)
        tool = next(m for m in model.calls[1][0] if isinstance(m, ToolMessage))
        self.assertEqual(len(json.loads(tool.content)["sources"]), 6)
        self.assertNotIn("internal IDs", "".join(e.get("content", "") for e in events))
        self.assertEqual([e["content"] for e in events if e["type"] == "token"], [reply.content])

    def test_followup_is_bounded_and_final_call_cannot_query(self):
        first = [{**self.paths[0], "source_ids": self.paths[0]["source_ids"][:1]}]
        second = [{**self.paths[0], "source_ids": self.paths[0]["source_ids"][1:]}]
        agent, model = self.agent([[query(first)], [query(second)], [spoken_reply("Complete answer.")]])
        events = []
        _reply, result = agent.run("Eligibility and exceptions?", [], emit=events.append)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(len(result.evidence), 2)
        self.assertEqual(model.calls[-1][1]["tool_choice"], "reply")
        next_schema = model.calls[1][2][0]["function"]["parameters"]["properties"]
        self.assertNotIn(first[0]["source_ids"][0], next_schema["source_ids"]["items"]["enum"])
        self.assertIn(second[0]["source_ids"][0], next_schema["source_ids"]["items"]["enum"])
        self.assertEqual([e["content"] for e in events if e["type"] == "token"], ["Complete answer."])

    def test_invalid_request_cannot_read_any_source(self):
        agent, model = self.agent([
            [query([{**self.paths[0], "source_ids": ["invented"]}])],
            [spoken_reply("I cannot establish that from the available evidence.")],
        ])
        _reply, result = agent.run("Missing fact?", [])
        self.assertEqual(len(model.calls), 2)
        self.assertFalse(result.evidence)
        self.assertIn("invalid", result.limitation)

    def test_each_turn_can_read_same_sources_without_previous_evidence(self):
        agent, model = self.agent([
            [query(self.paths[:1])], [spoken_reply("First answer")],
            [query(self.paths[:1])], [spoken_reply("Second answer")],
        ])
        agent.run("Question one", [])
        _reply, result = agent.run("Question two", [{"role": "assistant", "text": "First answer"}])
        self.assertEqual(len(result.evidence), 2)
        self.assertFalse(any(isinstance(m, ToolMessage) for m in model.calls[2][0]))

    def test_graph_routes_selected_provider_and_does_not_call_old_answer_model(self):
        normal, model = self.agent([[query(self.paths[:2])], [spoken_reply("Luna answer.")]])
        graph, decisions, old_model = make_agent([])
        graph.normal_agent = normal
        events = list(graph.stream("Hostels and scholarships?", config={"configurable": {
            "thread_id": "normal", "retrieval_provider": "llm_batch",
        }}))
        self.assertEqual(len(model.calls), 2)
        self.assertFalse(decisions.calls)
        self.assertFalse(old_model.calls)
        self.assertEqual(events[-1]["full_content"], "Luna answer.")

    def test_provider_switch_retains_context(self):
        graph, _decisions, old_model = make_agent([])
        normal, model = self.agent([[spoken_reply("Hi from Luna")], [spoken_reply("Follow-up")]])
        graph.normal_agent = normal
        config = {"configurable": {"thread_id": "switch-normal", "retrieval_provider": "llm_batch"}}
        graph.invoke("Hello", config=config)
        graph.invoke("And fees?", config=config)
        self.assertIn("Hi from Luna", str(model.calls[1][0]))
        self.assertFalse(old_model.calls)


class NormalLLMAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_speech_starts_before_reply_generation_finishes(self):
        from backend.test_voice_response import FakeSarvamClient, FakeTtsSocket
        from backend.voice_response import VoiceResponse, synthesize_response

        started = asyncio.Event()
        release = asyncio.Event()

        class PausingModel(ScriptedModel):
            def bind_tools(self, *_args, **_kwargs):
                class Binding:
                    async def astream(self, *_args, **_kwargs):
                        yield reply_chunk('{"text":"First sentence. ', first=True)
                        await release.wait()
                        yield reply_chunk('Second sentence."}')
                return Binding()

        agent = NormalLLMAgent(batch_store(), model=PausingModel([]))
        graph, _decisions, _old_model = make_agent([])
        graph.normal_agent = agent
        graph.is_voice = True
        owner = VoiceResponse(7, "en-IN")
        tts = FakeTtsSocket()
        tts.convert.side_effect = lambda _text: started.set()
        events = []

        async def producer():
            async for event in graph.astream("Hello", config={"configurable": {
                "thread_id": "stream-to-speech", "retrieval_provider": "llm_batch",
            }}):
                events.append(event)
                if event["type"] == "token":
                    await owner.put_text(event["content"])
            await owner.text_queue.put(None)

        task = asyncio.create_task(synthesize_response(
            owner, FakeSarvamClient(tts), unittest.mock.AsyncMock(), unittest.mock.AsyncMock(),
            lambda _response: None, producer,
        ))
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.assertFalse(task.done())
            tts.convert.assert_awaited_once_with("First sentence.")
            release.set()
            await asyncio.wait_for(task, 1)
            self.assertEqual(events[-1]["full_content"], "First sentence. Second sentence.")
            self.assertEqual([call.args[0] for call in tts.convert.await_args_list], ["First sentence.", "Second sentence."])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_concurrent_turns_do_not_share_reads_or_evidence(self):
        store = batch_store()
        selection = paths_for(store)[:1]

        class ConcurrentModel(ScriptedModel):
            def bind_tools(self, *_args, **_kwargs):
                class Binding:
                    async def astream(self, messages, **kwargs):
                        await asyncio.sleep(0)
                        if not isinstance(messages[-1], ToolMessage):
                            yield query(selection)
                        else:
                            question = next(m.content for m in messages if m.content in {"First question", "Second question"})
                            yield spoken_reply(question)
                return Binding()

        normal = NormalLLMAgent(store, model=ConcurrentModel([]))
        first, second = await asyncio.gather(
            normal.arun("First question", []), normal.arun("Second question", []),
        )
        self.assertEqual(first[0].content, "First question")
        self.assertEqual(second[0].content, "Second question")
        self.assertEqual(len(first[1].evidence), 2)
        self.assertEqual(len(second[1].evidence), 2)
        self.assertIsNot(first[1].evidence, second[1].evidence)

    async def test_async_voice_preserves_language_and_streams_only_reply(self):
        store = batch_store()
        model = ScriptedModel([[query(paths_for(store)[:2])], [spoken_reply("ਸਰੋਤ ਅਨੁਸਾਰ ਜਵਾਬ")]])
        normal = NormalLLMAgent(store, model=model)
        graph, _decisions, old_model = make_agent([])
        graph.normal_agent = normal
        graph.is_voice = True
        events = [e async for e in graph.astream("Hostels?", config={"configurable": {
            "thread_id": "voice-normal", "retrieval_provider": "llm_batch", "response_language": "pa-IN",
        }})]
        self.assertIn("Punjabi (pa-IN)", model.calls[0][0][0].content)
        self.assertIn("voice call", model.calls[0][0][0].content)
        self.assertFalse(old_model.calls)
        self.assertEqual(events[-1]["full_content"], "ਸਰੋਤ ਅਨੁਸਾਰ ਜਵਾਬ")

    async def test_deadline_and_cancellation_stop_pending_model(self):
        class HangingModel(ScriptedModel):
            def bind_tools(self, *_args, **_kwargs):
                class Binding:
                    async def astream(self, *_args, **_kwargs):
                        await asyncio.Event().wait()
                        yield AIMessageChunk(content="Must never speak")
                return Binding()

        normal = NormalLLMAgent(batch_store(), model=HangingModel([]))
        normal.timeout = 0.02
        with self.assertRaises(TimeoutError):
            await normal.arun("Hello", [])
        normal.timeout = 15
        task = asyncio.create_task(normal.arun("Hello", []))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
