import asyncio
import unittest
from unittest.mock import patch

from backend.voice_activity import CHECK_INS, VoiceActivity


class VoiceActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_states_wait_for_a_full_idle_period_after_completion(self):
        for flag in ("user_speaking", "awaiting_transcript", "answering", "response_pending", "playback_active", "playback_paused", "interruption_pending"):
            with self.subTest(flag=flag):
                activity = VoiceActivity(started=True)
                setattr(activity, flag, True)
                attempts = []

                async def wait(awaitable, timeout, *, attempts=attempts, activity=activity, flag=flag):
                    awaitable.close()
                    attempts.append(timeout)
                    if len(attempts) == 1:
                        raise TimeoutError  # 60 seconds while busy cannot trigger a check-in.
                    if len(attempts) == 2:
                        setattr(activity, flag, False)
                        activity.touch()  # Completion restarts the idle countdown.
                        return True
                    raise TimeoutError  # Now a full idle period has elapsed.

                with patch("backend.voice_activity.asyncio.wait_for", side_effect=wait):
                    await activity.wait_for_idle()
                self.assertEqual(attempts, [60, 60, 60])

    async def test_activity_repeatedly_restarts_idle_wait(self):
        activity = VoiceActivity(started=True)
        attempts = []

        async def wait(awaitable, timeout):
            awaitable.close()
            attempts.append(timeout)
            if len(attempts) <= 3:
                activity.touch()
                return True
            raise TimeoutError

        with patch("backend.voice_activity.asyncio.wait_for", side_effect=wait):
            await activity.wait_for_idle()
        self.assertEqual(attempts, [60] * 4)

    async def test_idle_wait_is_cancellable(self):
        activity = VoiceActivity(started=True)
        task = asyncio.create_task(activity.wait_for_idle())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    def test_check_in_languages_and_call_isolation(self):
        self.assertTrue(any("\u0a00" <= c <= "\u0a7f" for c in CHECK_INS["pa-IN"]))
        self.assertTrue(any("\u0900" <= c <= "\u097f" for c in CHECK_INS["hi-IN"]))
        self.assertIsNone(CHECK_INS.get("bn-IN"))
        first, second = VoiceActivity(started=True), VoiceActivity()
        first.touch()
        self.assertFalse(second.changed.is_set())
        self.assertFalse(second.idle)


if __name__ == "__main__":
    unittest.main()
