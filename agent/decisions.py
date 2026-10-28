"""OpenRouter adapter for OpenAI Decisions and the bounded PageIndex retrieval controller."""

import os
import threading

import httpx
from langsmith import traceable

from .decision_tracing import _trace_inputs, _trace_model, _trace_outputs


class DecisionError(RuntimeError):
    """A decision failed without exposing upstream bodies or credentials."""


class DecisionsClient:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.model = "openai/gpt-6-luna-decisions"
        self._sync = None
        self._async = None
        self._init_lock = threading.Lock()

    def _options(self):
        key = self.api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not key.strip():
            raise DecisionError("Missing OPENROUTER_API_KEY")
        return {
            "base_url": "https://openrouter.ai/api/alpha/",
            "headers": {"Authorization": f"Bearer {key}"},
            "http2": True,
        }

    def _payload(self, state, questions):
        return {"model": self.model, "state": state, "questions": questions}

    @staticmethod
    def _response(response, questions):
        response.raise_for_status()
        result = response.json()
        answers = result["answers"]
        if not isinstance(answers, dict):
            raise TypeError("Expected named decision answers")
        if set(answers) != set(questions):
            raise ValueError("Missing or unexpected decision answers")
        return result

    @traceable(
        name="openai_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["openai", "retrieval"],
    )
    def decide(self, state, questions, timeout):
        _trace_model(self.model, "openrouter")
        with self._init_lock:
            if self._sync is None:
                self._sync = httpx.Client(**self._options())
        try:
            response = self._sync.post(
                "decisions", json=self._payload(state, questions), timeout=timeout
            )
            return self._response(response, questions)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise DecisionError("OpenAI Decisions request failed") from None

    @traceable(
        name="openai_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["openai", "retrieval"],
    )
    async def adecide(self, state, questions, timeout):
        _trace_model(self.model, "openrouter")
        with self._init_lock:
            if self._async is None:
                self._async = httpx.AsyncClient(**self._options())
        try:
            response = await self._async.post(
                "decisions", json=self._payload(state, questions), timeout=timeout
            )
            return self._response(response, questions)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise DecisionError("OpenAI Decisions request failed") from None

    def close(self):
        if self._sync is not None:
            self._sync.close()
            self._sync = None

    async def aclose(self):
        self.close()
        if self._async is not None:
            await self._async.aclose()
            self._async = None
