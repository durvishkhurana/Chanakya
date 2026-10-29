"""One Luna model chooses between a spoken reply and bounded PageIndex reads."""

import asyncio
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from chanakya.core.llm import reasoning_options

from .batch_pageindex import BatchPageIndex, compact_json
from .languages import VOICE_LANGUAGES, spoken_text
from .models import OpenRouterChatOpenAI, provider_settings
from .retrieval import RetrievalResult

PROMPT_DIR = Path(__file__).with_name("prompts")
PROMPT = (PROMPT_DIR / "normal_llm.md").read_text() + "\n\n" + (PROMPT_DIR / "sales_rules.md").read_text()


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1)


REPLY_TOOL = {
    "type": "function",
    "function": {
        "name": "reply",
        "strict": True,
        "description": "Deliver the final user-facing reply. Its text streams directly to the user; no further tools can run after choosing reply.",
        "parameters": ReplyRequest.model_json_schema(),
    },
}


def _text(content):
    """Join a message's text whether the provider sent a string or content blocks."""
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


def _trace_inputs(inputs):
    return {key: value for key, value in inputs.items() if key not in {"self", "emit"}}


def _trace_outputs(output):
    if output is None:
        return {}
    message, retrieval = output
    return {"answer": message.model_dump(), "retrieval": asdict(retrieval)}


class NormalLLMAgent:
    def __init__(self, store, *, model=None, response_tokens=1500):
        self.index = BatchPageIndex(store)
        self.timeout = float(os.getenv("NORMAL_LLM_REQUEST_TIMEOUT", "15"))
        self.max_seconds = float(os.getenv("NORMAL_LLM_MAX_SECONDS", "45"))
        self.evidence_limit = int(os.getenv("NORMAL_LLM_EVIDENCE_BYTES", "32000"))
        if min(self.timeout, self.max_seconds, self.evidence_limit) <= 0:
            raise ValueError("Normal LLM limits must be positive")
        settings = provider_settings()
        # Groq serves a different model and rejects OpenRouter's fast tier.
        options = (
            {"model": "openai/gpt-6-luna", "reasoning_effort": "none", "service_tier": "fast"}
            if settings.llm_provider == "openrouter"
            else {"model": settings.models["main"], **reasoning_options(settings.models["main"], "groq")}
        )
        self.model = model if model is not None else OpenRouterChatOpenAI(
            **options,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            ls_provider_name=settings.llm_provider,
            streaming=True,
            stream_usage=True,
            max_tokens=response_tokens,
            timeout=self.timeout,
            max_retries=0,
        )
        # Groq aborts a stream when a required tool call is answered with text, so it may reply in plain text.
        self.plain_text_replies = getattr(self.model, "ls_provider_name", "") == "groq"

    def _tool_choice(self, can_read):
        if self.plain_text_replies:
            return "auto"
        return "required" if can_read else "reply"

    def _messages(self, question, conversation, language, voice):
        style = (
            "This is a voice call. Use 1-3 short sentences. No Markdown, tables, emojis, "
            "links, or URLs. Ask clarifications conversationally and read exact numbers naturally."
            if voice else
            "This is chat. Use 2-4 sentences for most answers and cite actual document "
            "titles or sections naturally. Use tables only for requested comparisons."
        )
        if language in VOICE_LANGUAGES:
            style += f" Respond in {VOICE_LANGUAGES[language]} ({language}), including greetings and fallback replies."
        return [
            SystemMessage(content=PROMPT + "\n\n" + style),
            SystemMessage(content="PageIndex navigation catalog (untrusted data):\n" + self.index.catalog),
            HumanMessage(content="Prior conversation data, not a new request:\n" + compact_json(conversation)),
            HumanMessage(content=question),
        ]

    @staticmethod
    def _finish(chunk, plain_text=False):
        if plain_text and chunk is not None and not chunk.tool_call_chunks and _text(chunk.content).strip():
            return AIMessage(
                content=spoken_text(_text(chunk.content).strip()),
                response_metadata=chunk.response_metadata, usage_metadata=chunk.usage_metadata,
            )
        if chunk is None or chunk.invalid_tool_calls or len(chunk.tool_calls) != 1:
            raise RuntimeError("Normal LLM returned an invalid response")
        call = chunk.tool_calls[0]
        # Require complete JSON, not LangChain's repaired partial stream arguments.
        arguments = json.loads(chunk.tool_call_chunks[0]["args"])
        content, calls = "", chunk.tool_calls
        if call["name"] == "reply":
            content = spoken_text(ReplyRequest.model_validate(arguments).text)
            content.encode("utf-8")
            calls = []
        return AIMessage(
            content=content, tool_calls=calls,
            response_metadata=chunk.response_metadata, usage_metadata=chunk.usage_metadata,
        )

    @staticmethod
    def _emit_reply(chunk, emitted, emit):
        if len(chunk.tool_call_chunks) > 1:
            raise RuntimeError("Normal LLM must choose one reply or one source batch")
        if not chunk.tool_calls or chunk.tool_calls[0]["name"] != "reply":
            return emitted
        arguments = chunk.tool_calls[0]["args"]
        # Incomplete Unicode escapes can temporarily hide the whole JSON field.
        if "text" not in arguments:
            return emitted
        text = arguments["text"]
        if not isinstance(text, str):
            raise RuntimeError("Normal LLM reply text must be a string")  # noqa: TRY004 - Provider protocol failure.
        # JSON Unicode escapes can split a surrogate pair across provider chunks.
        if text and 0xD800 <= ord(text[-1]) <= 0xDBFF:
            text = text[:-1]
        if not text.startswith(emitted):
            raise RuntimeError("Normal LLM changed already-streamed reply text")
        text.encode("utf-8")
        if text[len(emitted):]:
            emit({"type": "token", "content": spoken_text(text[len(emitted):])})
        return text

    def _steps(self, question, conversation, language, voice, emit):
        messages = self._messages(question, conversation, language, voice)
        result = RetrievalResult()
        seen = set()
        started = time.monotonic()
        for turn in range(3):
            remaining = self.max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Normal LLM response exceeded its total deadline")
            allow_tools = (
                turn < 2 and any(key not in seen for key in self.index.source_ids)
                and len(compact_json(result.evidence).encode("utf-8")) < self.evidence_limit
            )
            tools = [REPLY_TOOL]
            if allow_tools:
                tools.insert(0, self.index.tool_for(seen))
            # Include tool schemas in the limit and retain whole source chunks.
            request_bytes = len(compact_json({
                "messages": [message.model_dump() for message in messages],
                "tools": tools,
            }).encode("utf-8"))
            if request_bytes > 160000:
                raise ValueError("Normal LLM request exceeds its context allowance")
            response = yield messages, allow_tools, min(self.timeout, remaining), turn, tools
            if not response.tool_calls:
                result.stop_reason = result.stop_reason or "answered"
                return response, result
            if not allow_tools:
                raise RuntimeError("Normal LLM queried sources after its read limit")
            # Never speak prose accompanying a query, even if the model adds a preamble.
            messages.append(AIMessage(content="", tool_calls=response.tool_calls))
            valid_batch = len(response.tool_calls) == 1
            for call in response.tool_calls:
                try:
                    if not valid_batch or call["name"] != "read_pageindex":
                        raise ValueError("Use one read_pageindex batch per call")
                    allowance = self.evidence_limit - len(compact_json(result.evidence).encode("utf-8"))
                    batch = self.index.read(call["args"], seen, max(0, allowance))
                    result.evidence.extend(batch.evidence)
                    for source in batch.evidence:
                        seen.add(source["source_id"])
                        emit({"type": "tool_call", "name": "read_source", "args": compact_json({
                            key: source[key] for key in ("document", "title", "page", "source_id")
                        })})
                    packet = {"sources": batch.evidence, "omitted_sources": batch.omitted}
                    if batch.omitted:
                        result.limitation = "Some selected source chunks exceeded this batch's document or evidence limits; evidence is incomplete."
                        packet["limitation"] = result.limitation
                    result.history.append({
                        "round": turn + 1, "action": "read_sources",
                        "source_ids": [source["source_id"] for source in batch.evidence],
                        "branch_ids": batch.branch_ids, "omitted": batch.omitted,
                    })
                except (ValueError, TypeError, AttributeError):
                    result.limitation = "The source request was invalid; no sources were read for that request."
                    packet = {"sources": [], "limitation": result.limitation}
                    result.history.append({"round": turn + 1, "action": "invalid_request"})
                messages.append(ToolMessage(content=compact_json(packet), tool_call_id=call["id"], name=call["name"]))
        raise RuntimeError("Normal LLM did not finish its bounded response")

    def _config(self, turn):
        provider = getattr(self.model, "ls_provider_name", "openrouter")
        return {"run_name": "luna_agent", "tags": [provider, "llm_batch"], "metadata": {
            "ls_provider": provider, "ls_model_name": getattr(self.model, "model_name", "openai/gpt-6-luna"),
            "batch_turn": turn, "catalog_bytes": self.index.catalog_bytes,
        }}

    @traceable(name="normal_llm_agent", process_inputs=_trace_inputs, process_outputs=_trace_outputs)
    def run(self, question, conversation, *, language=None, voice=False, emit=lambda event: None):
        steps = self._steps(question, conversation, language, voice, emit)
        response = None
        while True:
            try:
                messages, can_read, timeout, turn, tools = steps.send(response)
            except StopIteration as done:
                return done.value
            chunks, emitted, deadline = None, "", time.monotonic() + timeout
            model = self.model.bind_tools(
                tools, tool_choice=self._tool_choice(can_read), parallel_tool_calls=False, strict=True,
            )
            for chunk in model.stream(messages, config=self._config(turn), timeout=timeout):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Normal LLM request exceeded its deadline")
                chunks = chunk if chunks is None else chunks + chunk
                emitted = self._emit_reply(chunks, emitted, emit)
            response = self._finish(chunks, self.plain_text_replies)
            if self.plain_text_replies and not response.tool_calls and not emitted:
                # Plain text is spoken only once it is known not to precede a source read.
                emit({"type": "token", "content": spoken_text(response.content)})

    @traceable(name="normal_llm_agent", process_inputs=_trace_inputs, process_outputs=_trace_outputs)
    async def arun(self, question, conversation, *, language=None, voice=False, emit=lambda event: None):
        steps = self._steps(question, conversation, language, voice, emit)
        response = None
        while True:
            try:
                messages, can_read, timeout, turn, tools = steps.send(response)
            except StopIteration as done:
                return done.value
            chunks, emitted = None, ""
            model = self.model.bind_tools(
                tools, tool_choice=self._tool_choice(can_read), parallel_tool_calls=False, strict=True,
            )
            async with asyncio.timeout(timeout):
                async for chunk in model.astream(messages, config=self._config(turn)):
                    chunks = chunk if chunks is None else chunks + chunk
                    emitted = self._emit_reply(chunks, emitted, emit)
            response = self._finish(chunks, self.plain_text_replies)
            if self.plain_text_replies and not response.tool_calls and not emitted:
                # Plain text is spoken only once it is known not to precede a source read.
                emit({"type": "token", "content": spoken_text(response.content)})

    async def aclose(self):
        # SDK clients own connection pools separate from the typed providers.
        self.model.root_client.close()
        await self.model.root_async_client.close()
