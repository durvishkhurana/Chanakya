# Phone demo runbook (I3)

Two ways to show a live call. Browser voice is the safe default; the phone path needs a streaming-capable Twilio
account. Tests never place real calls, and the phone path only ever dials the one allowlisted number in `.env`.

## A. Browser voice on a mission (recommended)

1. In `.env`: the LLM key (`GROQ_API_KEY` or `OPENROUTER_API_KEY`), `SARVAM_API_KEY`, `MISSIONS_ENABLED=true`,
   `PLANNER_ENABLED=true`, and `CALLING_HOURS=0-24` if you demo outside 9:00-21:00 IST.
2. Start the backend and the frontend (README, "Run locally").
3. Open `/missions`, select **Load demo signals**, then open a mission's live call (`/call/<mission id>`).
4. Select **Talk by voice instead** and speak as the merchant. The transcript, concern meter, planner and
   safety panels fill from the mission ledger as you talk.
5. Or pick a scenario in Mission Control and select **Run scenario**; it plays without a microphone.

## B. Phone call to your own number (Twilio)

Trial Twilio accounts block Media Streams, so this needs an upgraded account.

1. In `.env`: `TWILIO_ENABLED=true`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`,
   `TWILIO_ALLOWED_PHONE_NUMBER` (your own mobile), and `TWILIO_PUBLIC_BASE_URL` (the public HTTPS origin that
   reaches your backend, for example a tunnel). Keep `PLANNER_ENABLED=true` for the planning brain.
2. Start the backend, then place the call:

   ```bash
   .venv/bin/python -m backend.call_chanakya --request-id demo-1
   ```

   A repeated `--request-id` never redials. If the outcome is unknown, check the Twilio Console and run
   `--resolve-request demo-1`.
3. Answer on your mobile and speak as the merchant. Chanakya discloses that it is an AI first.

Phone calls are not yet tied to a mission, so they do not appear in the Live Call View; use path A to show the
dashboards.

## What happens when the network fails

| Failure | What the caller gets |
|---|---|
| LLM provider slow or down | Past `VOICE_LLM_TIMEOUT_MS` (default 4000 ms) the reply is the safe template line and the belief uses lexical evidence, so there is no long silence |
| LLM provider error | Same template and lexical fallbacks |
| Speech recognition drops | The browser shows "Speech recognition failed. Please reconnect." |
| Speech synthesis fails | The browser shows "Speech failed. Please try again." |
| Phone media socket closes | Twilio continues the call script: "This conversation has ended. Please call again if you need help." and hangs up, so a call is never left silent |
| Another call is in progress | The caller hears that Chanakya is on another call (one call at a time by default) |

## Backup video

Record path A once it works, in case the network fails during the demo. On Windows, Xbox Game Bar records the
browser window (Win+Alt+R starts and stops). Show: Mission Control, **Run scenario** for the card-machine sale,
the live call filling in, the link verified to DONE, then the distressed-merchant hand-off card. Keep the
recording out of the repository (no call recordings are committed); link it from the pitch instead.
