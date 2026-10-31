"""Browser protocol 2 adapter for the shared voice session."""

import logging
import os
import socket  # noqa: F401 - Existing tests inject DNS through this shared module.

from sarvamai import AsyncSarvamAI

from backend.voice_activity import VoiceActivity
from backend.voice_interruption import VoiceInterruptionClassifier
from backend.voice_session import run_voice_session
from backend.voice_transport import BrowserVoiceTransport

sarvam_client = AsyncSarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY", ""))
logger = logging.getLogger(__name__)


async def voice_pipeline(websocket, voice_agent, retrieval_provider="decisions"):
    transport = BrowserVoiceTransport(websocket)
    headers = getattr(websocket, "headers", None) or {}
    logger.info("Voice call opened from %s", headers.get("user-agent", "unknown browser"))
    await websocket.accept()
    await run_voice_session(
        transport, voice_agent, sarvam_client, retrieval_provider,
        classifier_factory=VoiceInterruptionClassifier, activity_factory=VoiceActivity,
    )
