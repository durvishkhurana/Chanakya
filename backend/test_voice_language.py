import unittest

from backend.voice_language import VoiceLanguage


class VoiceLanguageTests(unittest.TestCase):
    def test_negated_requests_do_not_select_unwanted_language(self):
        for text in (
            "Please do not speak in Hindi", "Don't reply in Punjabi",
            "I do not want you to speak in Hindi", "Never answer in Punjabi",
            "हिंदी में मत बोलिए", "ਹਿੰਦੀ ਵਿੱਚ ਗੱਲ ਨਾ ਕਰੋ",
        ):
            with self.subTest(text=text):
                self.assertEqual(VoiceLanguage().observe(text, "en-IN", 0.99), "en-IN")
        language = VoiceLanguage()
        self.assertEqual(language.observe("Don't reply in Hindi; please reply in Punjabi", "en-IN", 0.99), "pa-IN")

    def test_initial_punjabi_greeting_establishes_language(self):
        language = VoiceLanguage()
        self.assertEqual(language.observe("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "pa-IN", 0.99), "pa-IN")

    def test_low_confidence_cannot_establish_or_switch_language(self):
        language = VoiceLanguage()
        self.assertEqual(language.observe("What are hostel fees?", "hi-IN", 0.01), "en-IN")
        language.observe("What are hostel fees?", "en-IN", 0.99)
        for confidence in (0.01, float("nan"), float("inf"), -1, 2):
            self.assertEqual(language.observe("Tell me about admissions", "hi-IN", confidence), "en-IN")

    def test_short_or_single_mixed_language_turn_keeps_punjabi(self):
        language = VoiceLanguage()
        language.observe("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "pa-IN", 0.99)
        for text in ("Yes", "Okay thanks", "What about hostel charges?"):
            self.assertEqual(language.observe(text, "en-IN", 0.99), "pa-IN")

    def test_two_substantive_turns_allow_deliberate_switch(self):
        language = VoiceLanguage()
        language.observe("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "pa-IN", 0.99)
        self.assertEqual(language.observe("What are the hostel charges?", "en-IN", 0.95), "pa-IN")
        self.assertEqual(language.observe("Tell me about the mess fees", "en-IN", 0.95), "en-IN")

    def test_explicit_switch_overrides_input_language(self):
        language = VoiceLanguage()
        self.assertEqual(language.observe("Please reply in Punjabi", "en-IN", 0.99), "pa-IN")
        self.assertEqual(language.observe("हिंदी में बोलिए", "hi-IN", 0.99), "hi-IN")
        self.assertEqual(language.observe("ਪੰਜਾਬੀ ਵਿੱਚ ਗੱਲ ਕਰੋ", "pa-IN", 0.99), "pa-IN")

    def test_missing_confidence_and_invalid_detection(self):
        language = VoiceLanguage()
        self.assertEqual(language.observe("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "pa-IN"), "pa-IN")
        for detected in (None, "unknown", "auto", "invalid"):
            self.assertEqual(language.observe("What are the hostel fees?", detected), "pa-IN")
        self.assertEqual(language.observe("", "en-IN", 1), "pa-IN")

    def test_new_calls_do_not_share_language(self):
        first, second = VoiceLanguage(), VoiceLanguage()
        first.observe("ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "pa-IN", 0.99)
        self.assertEqual(second.current, "en-IN")


if __name__ == "__main__":
    unittest.main()
