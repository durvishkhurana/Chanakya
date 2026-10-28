import asyncio
import copy
import json
import unittest
from unittest.mock import patch

import httpx2
from langsmith import Client as LangSmithClient
from langsmith import tracing_context
from typesafe_sdk import RetryPolicy, TypeSafeClient

from agent.documents import DocumentStore
from agent.jev import JevClient
from agent.retrieval import RetrievalLimits, Retriever, json_bytes


def answer(action, target=None):
    answers = {
        "action": {
            "type": "choice",
            "choice": action,
            "confidence": 0.9,
            "probabilities": {
                "read_more": 0.95 if action == "read_more" else 0.05,
                "ready_to_answer": 0.95 if action == "ready_to_answer" else 0.05,
            },
        },
        "next_read": {
            "type": "choice",
            "choice": target,
            "confidence": 0.9,
            "probabilities": {target: 1.0} if target else {},
        },
    }
    return {
        "answers": answers,
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


def documents():
    return DocumentStore(
        {
            name: {
                "metadata": {"description": description},
                "tree": {
                    "result": [
                        {
                            "title": title,
                            "node_id": "0000",
                            "page_index": 1,
                            "text": text,
                        }
                    ]
                },
                "pages": {"result": [{"page_index": 1, "markdown": text}]},
            }
            for name, description, title, text in [
                ("fees", "Hostel fees", "Hostel fees", "Hostel fees are Rs. 50000."),
                (
                    "scholarships",
                    "Scholarship rules",
                    "Coverage",
                    "Scholarships exclude hostel fees.",
                ),
            ]
        }
    )


class ScriptedClient:
    def __init__(self, script):
        self.script = iter(script)
        self.calls = []

    def decide(self, state, questions, timeout):
        self.calls.append(copy.deepcopy((state, questions, timeout)))
        response = next(self.script)
        return response(state, questions) if callable(response) else response

    async def adecide(self, state, questions, timeout):
        return self.decide(state, questions, timeout)


def read_first(_state, questions):
    target = next(iter(questions["next_read"]["criteria"]))
    return answer("read_more", target)


class RetrievalTests(unittest.TestCase):
    def test_other_documents_excludes_current_book_but_allows_explicit_return(self):
        store = documents()
        first = store.roots[0]
        first_source = store.targets[first].children[0]
        pages = store.targets[first].children[1]
        client = ScriptedClient([
            answer("read_more", first),
            answer("read_more", first_source),
            answer("read_more", pages),
            answer("read_more", "other_documents"),
            answer("read_more", "resume_document"),
            answer("ready_to_answer"),
        ])
        result = Retriever(store, client).run("Fees and scholarship?", [])
        self.assertEqual(result.stop_reason, "ready_to_answer")
        alternatives = client.calls[4][0]["unread_sources"]
        self.assertNotIn(first, alternatives)
        self.assertIn("resume_document", alternatives)
        self.assertIn(store.roots[1], alternatives)
        self.assertNotIn(first_source, client.calls[5][0]["unread_sources"])

    def test_wrong_document_can_be_corrected_without_a_navigation_loop(self):
        store = documents()
        wrong, right = store.roots
        source = store.targets[right].children[0]
        client = ScriptedClient([
            answer("read_more", wrong),
            answer("read_more", "go_back"),
            answer("read_more", right),
            answer("read_more", source),
            answer("ready_to_answer"),
        ])
        result = Retriever(store, client).run("Scholarship coverage?", [])
        self.assertEqual(result.stop_reason, "ready_to_answer")
        self.assertEqual(result.evidence[0]["document"], "scholarships")

    def test_reading_more_text_shrinks_the_menu_and_preserves_complete_evidence(self):
        store = DocumentStore({
            "fees": {"tree": {"result": [
                {"title": f"Fee policy {index}", "summary": "policy details " * 25,
                 "text": f"Policy {index}: " + "₹ rules " * 450}
                for index in range(10)
            ]}}
        })
        client = ScriptedClient([read_first] * 12)
        result = Retriever(store, client).run("All fee policies?", [{"text": "a" * 4000}])
        self.assertEqual(result.stop_reason, "evidence_limit")
        self.assertGreater(len(result.evidence), 1)
        for source in result.evidence:
            self.assertEqual(source["text"], store.targets[source["source_id"]].text)
        for state, questions, _ in client.calls:
            self.assertLessEqual(json_bytes({"state": state, "questions": questions}), 28000)
            self.assertLessEqual(json_bytes(state["unread_sources"]), 6000)
        self.assertEqual(result.history[-1]["status"], "not_read")

    def test_very_long_navigation_labels_do_not_create_oversize_requests(self):
        store = DocumentStore({
            f"document-{index}": {
                "metadata": {"name": "Huge title " * 3000, "description": "₹" * 400},
                "tree": {"result": [{"text": "Small source"}]},
            }
            for index in range(30)
        })
        client = ScriptedClient([answer("ready_to_answer")])
        result = Retriever(store, client).run("Hello", [])
        self.assertEqual(result.stop_reason, "ready_to_answer")
        state, questions, _ = client.calls[0]
        self.assertLessEqual(json_bytes({"state": state, "questions": questions}), 28000)
        self.assertLessEqual(json_bytes(state["unread_sources"]), 6000)
        self.assertIn("more_candidates", state["unread_sources"])

    def test_large_section_list_does_not_block_the_selected_source(self):
        corpus = {
            "admissions": {
                "tree": {"result": [
                    {"title": f"Section {index}", "summary": "details " * 50,
                     "text": "Actual source text. " * 250}
                    for index in range(40)
                ]}
            }
        }
        corpus.update({
            f"other-{index}": {
                "metadata": {"description": "unrelated details " * 30},
                "tree": {"result": [{"text": "Unrelated source"}]},
            }
            for index in range(40)
        })
        store = DocumentStore(corpus)
        client = ScriptedClient([read_first, read_first, read_first,
                                 answer("ready_to_answer")])
        result = Retriever(store, client).run("Courses?", [])
        self.assertEqual(result.stop_reason, "ready_to_answer")
        self.assertTrue(result.evidence)
        self.assertEqual(result.evidence[0]["text"], "Actual source text. " * 250)
        for state, questions, _ in client.calls:
            self.assertLessEqual(json_bytes({"state": state, "questions": questions}), 28000)

    def test_opening_document_hides_unrelated_documents(self):
        client = ScriptedClient([read_first, answer("ready_to_answer")])
        Retriever(documents(), client).run("Hostel fees?", [])
        menu = client.calls[1][0]["unread_sources"]
        self.assertNotIn("scholarships", str(menu))
        self.assertIn("go_back", menu)

    def test_combined_calls_retrieve_multiple_documents_then_handoff(self):
        store = documents()
        first, second = store.roots
        first_source = store.targets[first].children[0]
        second_source = store.targets[second].children[0]
        client = ScriptedClient(
            [
                answer("read_more", first),
                answer("read_more", first_source),
                answer("read_more", "go_back"),
                answer("read_more", second),
                answer("read_more", second_source),
                answer("ready_to_answer", "ignored-invalid-target"),
            ]
        )
        result = Retriever(store, client).run("Can a scholarship pay hostel fees?", [])
        self.assertEqual(result.stop_reason, "ready_to_answer")
        self.assertEqual(
            {item["document"] for item in result.evidence}, {"fees", "scholarships"}
        )
        self.assertEqual(len(client.calls), 6)
        for state, questions, _timeout in client.calls:
            self.assertEqual(set(questions), {"action", "next_read"})
            self.assertEqual(
                set(state["unread_sources"]), set(questions["next_read"]["criteria"])
            )
            self.assertEqual(
                set(questions["action"]["criteria"]), {"read_more", "ready_to_answer"}
            )
            self.assertLessEqual(
                json_bytes({"state": state, "questions": questions}), 28000
            )
        self.assertEqual(client.calls[1][0]["evidence"], [])
        self.assertEqual(client.calls[0][0]["unread_source_count"], 2)
        self.assertFalse(client.calls[0][0]["has_more_candidates"])
        self.assertIn("Hostel fees", str(client.calls[0][0]["unread_sources"]))
        self.assertIn("Hostel fees", client.calls[2][0]["evidence"][0]["text"])
        for index, (_state, questions, _timeout) in enumerate(client.calls[1:], 1):
            prior = result.history[index - 1].get("target_id")
            self.assertNotIn(prior, questions["next_read"]["criteria"])

    def test_ready_can_request_clarification_without_fetching_a_source(self):
        client = ScriptedClient([answer("ready_to_answer")])
        result = Retriever(documents(), client).run("fees", [])
        self.assertEqual(result.evidence, [])
        self.assertEqual(result.stop_reason, "ready_to_answer")

    def test_invalid_target_is_never_executed(self):
        retriever = Retriever(
            documents(), ScriptedClient([answer("read_more", "forged")])
        )
        with patch.object(retriever, "fetch") as fetch:
            result = retriever.run("Hostel fees?", [])
        fetch.assert_not_called()
        self.assertEqual(result.stop_reason, "invalid_decision")

    def test_round_limit_is_distinct_from_jev_readiness(self):
        result = Retriever(
            documents(), ScriptedClient([read_first]), RetrievalLimits(max_rounds=1)
        ).run("Hostel fees?", [])
        self.assertEqual(result.stop_reason, "round_limit")
        self.assertEqual(result.history[-1]["action"], "read_more")
        self.assertTrue(result.limitation)

    def test_missing_sources_do_not_trigger_an_api_request(self):
        client = ScriptedClient([])
        result = Retriever(DocumentStore({}), client).run("fees", [])
        self.assertEqual(result.stop_reason, "sources_exhausted")
        self.assertEqual(client.calls, [])

    def test_source_exhaustion_preserves_fetched_evidence(self):
        store = DocumentStore({"one": {"tree": {"result": [{"text": "Evidence"}]}}})
        result = Retriever(store, ScriptedClient([read_first, read_first])).run(
            "question", []
        )
        self.assertEqual(result.stop_reason, "sources_exhausted")
        self.assertEqual(result.evidence[0]["text"], "Evidence")

    def test_large_input_stops_before_sending_an_oversize_request(self):
        client = ScriptedClient([])
        result = Retriever(documents(), client).run("a" * 30000, [])
        self.assertEqual(result.stop_reason, "input_limit")
        self.assertEqual(client.calls, [])

    def test_evidence_limit_never_silently_truncates_source(self):
        result = Retriever(
            documents(),
            ScriptedClient([read_first, read_first]),
            RetrievalLimits(max_evidence_bytes=1),
        ).run("fees", [])
        self.assertEqual(result.stop_reason, "evidence_limit")
        self.assertEqual(result.evidence, [])

    def test_pagination_makes_later_sources_reachable(self):
        store = DocumentStore(
            {
                str(index): {"metadata": {"description": "details " * 40}}
                for index in range(60)
            }
        )
        chosen = []

        def paginate(state, questions):
            menu = questions["next_read"]["criteria"]
            self.assertEqual(set(state["unread_sources"]), set(menu))
            self.assertTrue(state["has_more_candidates"])
            self.assertEqual(state["unread_source_count"], len(store.roots))
            self.assertLessEqual(
                json_bytes({"state": state, "questions": questions}), 6000
            )
            chosen.extend(key for key in menu if key != "more_candidates")
            return answer("read_more", "more_candidates")

        result = Retriever(
            store,
            ScriptedClient([paginate] * 10),
            RetrievalLimits(max_request_bytes=6000),
        ).run("question", [])
        self.assertEqual(set(chosen), set(store.roots))
        self.assertEqual(result.stop_reason, "no_progress")

    def test_each_run_starts_with_fresh_retrieval_state(self):
        client = ScriptedClient([answer("ready_to_answer"), answer("ready_to_answer")])
        retriever = Retriever(documents(), client)
        retriever.run("fees", [])
        retriever.run("scholarships", [])
        self.assertEqual(client.calls[1][0]["history"], [])
        self.assertEqual(client.calls[1][0]["evidence"], [])


class RetrievalAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_matches_sync_result(self):
        client = ScriptedClient([read_first, read_first, answer("ready_to_answer")])
        result = await Retriever(documents(), client).arun("Hostel fees?", [])
        self.assertEqual(result.stop_reason, "ready_to_answer")
        self.assertEqual(len(result.evidence), 1)

    async def test_timeout_returns_a_limitation_without_retry(self):
        class SlowClient:
            async def adecide(self, *_args):
                await asyncio.Event().wait()

        result = await Retriever(
            documents(), SlowClient(), RetrievalLimits(request_timeout=0.01)
        ).arun("fees", [])
        self.assertEqual(result.stop_reason, "decision_error")
        self.assertIn("TimeoutError", result.limitation)

    async def test_cancellation_propagates_to_pending_jev_request(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        class PendingClient:
            async def adecide(self, *_args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        task = asyncio.create_task(
            Retriever(documents(), PendingClient()).arun("fees", [])
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(cancelled.is_set())


class JevTransportTests(unittest.TestCase):
    def test_langsmith_records_jev_inputs_and_decision_without_credentials(self):
        trace_client = LangSmithClient(
            api_key="local-tracing-key", auto_batch_tracing=False
        )
        jev = JevClient(api_key="credential-must-not-appear")
        jev._sync = TypeSafeClient(
            api_key="credential-must-not-appear",
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(
                    200, json=answer("ready_to_answer", "source")
                )
            ),
        )
        questions = {
            "action": {
                "type": "choice",
                "instructions": "Continue?",
                "criteria": {"read_more": None, "ready_to_answer": None},
            },
            "next_read": {
                "type": "choice",
                "instructions": "Where?",
                "criteria": {"source": None},
            },
        }
        try:
            with (
                patch.object(LangSmithClient, "create_run") as created,
                patch.object(LangSmithClient, "update_run") as updated,
                tracing_context(enabled=True, client=trace_client),
            ):
                jev.decide({"question": "Hostel fees?"}, questions, 1)
            self.assertEqual(created.call_count, 1)
            self.assertEqual(created.call_args.kwargs["name"], "jev_decision")
            self.assertEqual(created.call_args.kwargs["run_type"], "llm")
            self.assertIn("questions", created.call_args.kwargs["inputs"])
            self.assertNotIn("self", created.call_args.kwargs["inputs"])
            self.assertIn("ready_to_answer", str(updated.call_args.kwargs["outputs"]))
            self.assertEqual(
                updated.call_args.kwargs["outputs"]["usage_metadata"],
                {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            )
            metadata = updated.call_args.kwargs["extra"]["metadata"]
            self.assertEqual(metadata["ls_provider"], "typesafe")
            self.assertEqual(metadata["ls_model_name"], "jev-1.13.0")
            self.assertNotIn("credential-must-not-appear", str(created.call_args))
            self.assertNotIn("credential-must-not-appear", str(updated.call_args))
        finally:
            jev.close()
            trace_client.close()

    def test_sdk_sends_both_questions_in_exactly_one_http_request(self):
        requests = []

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx2.Response(200, json=answer("read_more", "t00001"))

        sdk = TypeSafeClient(
            api_key="test-key",
            retry=RetryPolicy(max_retries=0),
            transport=httpx2.MockTransport(respond),
        )
        client = JevClient()
        client._sync = sdk
        questions = {
            "action": {
                "type": "choice",
                "instructions": "Continue?",
                "criteria": {"read_more": None, "ready_to_answer": None},
            },
            "next_read": {
                "type": "choice",
                "instructions": "Where?",
                "criteria": {"t00001": None, "t00002": None},
            },
        }
        try:
            response = client.decide({"question": "fees"}, questions, 1)
        finally:
            client.close()
        self.assertEqual(len(requests), 1)
        self.assertEqual(set(requests[0]["questions"]), {"action", "next_read"})
        self.assertEqual(response["answers"]["next_read"]["choice"], "t00001")

    def test_errors_do_not_copy_secrets_into_handoff(self):
        def fail(*_args):
            raise RuntimeError("secret-test-key")

        client = ScriptedClient([])
        client.decide = fail
        result = Retriever(documents(), client).run("fees", [])
        self.assertEqual(result.stop_reason, "decision_error")
        self.assertNotIn("secret-test-key", result.limitation)
