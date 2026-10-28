"""An idle check-in waits for silence after all call activity has finished."""

import asyncio
from dataclasses import dataclass, field

CHECK_INS = {
    "en-IN": "I'm still here. Would you like help choosing a Paytm payment product?",
    "hi-IN": "मैं अभी भी यहीं हूँ। Paytm के पेमेंट प्रोडक्ट के बारे में कोई सवाल हो तो पूछिए।",
    "pa-IN": "ਮੈਂ ਅਜੇ ਵੀ ਇੱਥੇ ਹਾਂ। Paytm ਦੇ ਪੇਮੈਂਟ ਪ੍ਰੋਡਕਟ ਬਾਰੇ ਕੋਈ ਸਵਾਲ ਹੋਵੇ ਤਾਂ ਪੁੱਛੋ।",
}


@dataclass
class VoiceActivity:
    started: bool = False
    user_speaking: bool = False
    awaiting_transcript: bool = False
    answering: bool = False
    response_pending: bool = False
    playback_active: bool = False
    playback_paused: bool = False
    interruption_pending: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def idle(self):
        return self.started and not (
            self.user_speaking or self.awaiting_transcript or self.answering
            or self.response_pending or self.playback_active
            or self.playback_paused or self.interruption_pending
        )

    def touch(self):
        self.changed.set()

    async def wait_for_idle(self, seconds=60):
        while True:
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=seconds)
            except TimeoutError:
                if self.idle:
                    return
