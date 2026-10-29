import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main


class VoiceApiTests(unittest.TestCase):
    def test_blank_keys_allow_startup_but_report_unconfigured(self):
        blank = {"OPENROUTER_API_KEY": "", "GROQ_API_KEY": "", "LLM_PROVIDER": "", "SARVAM_API_KEY": "",
                 "TWILIO_ENABLED": "false", "VOICE_INTERRUPTION_ENABLED": "false"}
        with patch.dict(os.environ, blank), TestClient(main.app) as client:
            result = client.get("/api/health").json()
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["configured"])
            self.assertEqual(result["missing"], ["OPENROUTER_API_KEY", "SARVAM_API_KEY"])
            with client.websocket_connect("/api/voice/ws") as socket:
                error = socket.receive_json()
                self.assertEqual(error["type"], "voice_error")
                self.assertIn("not configured", error["message"])

    def test_no_copied_chat_or_upload_routes(self):
        paths = {getattr(route, "path", None) for route in main.app.routes}
        self.assertIn("/api/voice/ws", paths)
        self.assertFalse(paths.intersection({"/api/chat", "/api/chat/voice", "/api/stt", "/api/tts"}))

    def test_contextual_interruption_requires_classifier_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "configured", "SARVAM_API_KEY": "configured", "TYPESAFE_API_KEY": "", "VOICE_INTERRUPTION_ENABLED": "true"}):
            self.assertEqual(main.missing_configuration(), ["TYPESAFE_API_KEY"])

    def test_groq_key_configures_the_agent_while_openrouter_is_absent(self):
        env = {"OPENROUTER_API_KEY": "", "GROQ_API_KEY": "configured", "LLM_PROVIDER": "",
               "SARVAM_API_KEY": "configured", "VOICE_INTERRUPTION_ENABLED": "false"}
        with patch.dict(os.environ, env):
            self.assertEqual(main.missing_configuration(), [])
            self.assertEqual(main.missing_configuration("decisions"), ["OPENROUTER_API_KEY"])
        with patch.dict(os.environ, {**env, "OPENROUTER_API_KEY": "configured", "GROQ_API_KEY": ""}):
            self.assertEqual(main.llm_key_name(), "OPENROUTER_API_KEY")
