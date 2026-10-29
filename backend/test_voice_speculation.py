"""The voice session hands partial transcripts to agents that can plan while listening."""

import asyncio
import os
import unittest
from unittest.mock import patch

from backend import voice_pipeline as voice_pipeline_module
from backend.test_voice_pipeline import AutoTts, OwnedStreamingService, QueueStt, RecordingAgent, RecordingBrowser


class SpeculatingAgent(RecordingAgent):
    def __init__(self):
        super().__init__("Sure.")
        self.prepared = []

    async def prepare(self, text, thread_id, language):
        self.prepared.append((text, thread_id, language))


class VoiceSpeculationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.browser, self.stt = RecordingBrowser(), QueueStt()
        client = type("Client", (), {})()
        client.speech_to_text_realtime_streaming = OwnedStreamingService(lambda: self.stt)
        client.text_to_speech_streaming = OwnedStreamingService(AutoTts)
        self.patches = [patch.object(voice_pipeline_module, "sarvam_client", client),
                        patch.object(voice_pipeline_module.socket, "getaddrinfo", return_value=[]),
                        patch.dict(os.environ, {"VOICE_INTERRUPTION_ENABLED": "false", "PLANNING_WHILE_LISTENING": "true"})]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        await self.browser.command("end_call")
        await asyncio.wait_for(self.task, 1)
        for item in reversed(self.patches):
            item.stop()

    async def run_call(self, agent):
        await self.browser.command("start_call", protocol_version=2, thread_id="spec-call")
        self.task = asyncio.create_task(voice_pipeline_module.voice_pipeline(self.browser, agent))
        await self.browser.event("voice_ready")
        await self.stt.event("RealtimeTranscriptPartial", "Rent kitna")
        await self.browser.event("partial_transcript")
        await self.stt.event("RealtimeTranscriptFinal", "Rent kitna hai?")
        await self.browser.event("tts_done", 1)

    async def test_partials_reach_an_agent_that_can_prepare_turns(self):
        agent = SpeculatingAgent()
        await self.run_call(agent)
        self.assertEqual(agent.prepared, [("Rent kitna", "spec-call", "en-IN")])
        self.assertEqual([call[0] for call in agent.calls], ["Rent kitna hai?"])

    async def test_the_flag_keeps_speculation_off_by_default(self):
        agent = SpeculatingAgent()
        with patch.dict(os.environ, {"PLANNING_WHILE_LISTENING": "false"}):
            await self.run_call(agent)
        self.assertEqual(agent.prepared, [])

    async def test_agents_without_prepare_are_unchanged(self):
        agent = RecordingAgent("Sure.")
        await self.run_call(agent)
        self.assertEqual([call[0] for call in agent.calls], ["Rent kitna hai?"])


if __name__ == "__main__":
    unittest.main()
