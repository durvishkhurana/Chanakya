"""One TypeSafe request returns both the action and next retrieval target."""

import os
import threading

import httpx2
from langsmith import traceable
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeClient

from .decision_tracing import _trace_inputs, _trace_model, _trace_outputs


class JevClient:
    def __init__(self, api_key=None, model=None, *, purpose="retrieval"):
        self.api_key = api_key
        self.model = model or os.getenv("JEV_MODEL", "jev-1.13.0")
        self.purpose = purpose
        self._sync = None
        self._async = None
        self._init_lock = threading.Lock()

    def _options(self):
        key = self.api_key or os.getenv("TYPESAFE_API_KEY", "")
        if not key.strip():
            raise RuntimeError("Missing TYPESAFE_API_KEY")
        return {
            "api_key": key,
            "model": self.model,
            # A single request per round, without hidden retry delays.
            "retry": RetryPolicy(max_retries=0),
        }

    @traceable(
        name="jev_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["jev"],
    )
    def decide(self, state, questions, timeout):
        _trace_model(self.model, "typesafe", self.purpose)
        with self._init_lock:
            if self._sync is None:
                self._sync = TypeSafeClient(
                    **self._options(), http_client=httpx2.Client(http2=True)
                )
        response = self._sync.system_one(state, questions, timeout=timeout)
        _trace_model(response.model or self.model, "typesafe", self.purpose)
        return response.model_dump(mode="json")

    @traceable(
        name="jev_decision",
        run_type="llm",
        process_inputs=_trace_inputs,
        process_outputs=_trace_outputs,
        tags=["jev"],
    )
    async def adecide(self, state, questions, timeout):
        _trace_model(self.model, "typesafe", self.purpose)
        with self._init_lock:
            if self._async is None:
                self._async = AsyncTypeSafeClient(
                    **self._options(), http_client=httpx2.AsyncClient(http2=True)
                )
        response = await self._async.system_one(state, questions, timeout=timeout)
        _trace_model(response.model or self.model, "typesafe", self.purpose)
        return response.model_dump(mode="json")

    def close(self):
        if self._sync is not None:
            self._sync.close()
            self._sync = None

    async def aclose(self):
        self.close()
        if self._async is not None:
            await self._async.aclose()
            self._async = None
