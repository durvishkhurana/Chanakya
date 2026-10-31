# Phone demo runbook (I3)

Three ways to show a live call. The recommended one is C: you speak as the merchant on your own phone, in the browser,
while the laptop shows Chanakya's thinking. It needs no telephone account. The Twilio path (B) needs a
streaming-capable account. Tests never place real calls, and the Twilio path only ever dials the one allowlisted
number in `.env`.

## C. Your phone in the browser (recommended)

### One-time setup

1. Install cloudflared once: `winget install Cloudflare.cloudflared`.
2. In `.env`, besides the keys (`GROQ_API_KEY` or `OPENROUTER_API_KEY`, and `SARVAM_API_KEY`):

   ```bash
   MISSIONS_ENABLED=true
   PLANNER_ENABLED=true
   COACH_ENABLED=true
   WINBACK_ENABLED=true
   APPROVAL_TOOLS=book_field_visit
   CALLING_HOURS=0-24
   DEMO_TOOLS_ENABLED=true
   ```

3. Start the backend on port 8000 and the frontend on port 3000 (README, "Run locally"). If the frontend runs on
   another port, set `PHONE_LINK_PORT` to it.
4. Optional, to get the onboarding link by email on the phone: in `.env` set `LINK_EMAIL_ENABLED=true`,
   `LINK_EMAIL_TO` (your own address, the only one it ever writes to), `SMTP_USER` and `SMTP_PASSWORD`. With Gmail,
   `SMTP_USER` is the Gmail address and `SMTP_PASSWORD` an app password (Google Account, Security, App passwords;
   it needs 2-Step Verification). Restart the backend; its log says "Onboarding links sent on live calls are emailed".

### Each demo

1. Start from a fresh ledger: stop the backend, delete `.state/chanakya.db` and `.state/mock_systems.db`, start it
   again. A merchant already onboarded in an earlier run makes the next sale to them stop, correctly.
   Never run `scripts/demo/e2e_track_b.py` against the ledger you demo on, for the same reason.
   To run one mission again without wiping everything, select **Reset to queue** on it in Mission Control, or
   **Reset this call** under **Demo tools** on its call page. The old run stays in the ledger, hidden from the board,
   the mock systems forget what it wrote (the merchant's products go back to the seed), and a fresh copy waits in the
   queue.
2. On the laptop open `/missions`, select **Load demo signals**, open a mission's live call (`/call/<mission id>`).
3. Under **Demo tools** select **Connect phone** (up to 45 seconds). Scan the QR code with the phone, then tap the
   mic button and allow the microphone.
4. Speak as the merchant. The laptop's Live Call View fills as you talk.
5. When done, select **Save run log**, then **Disconnect phone**. Stopping the backend also closes the link.

While the link is open anyone who has its URL can open the demo and use your API keys, so disconnect after each
demo. Only the laptop can open or close the link or save a run; requests through the tunnel are refused.

### Demo flow (about 6 minutes; the starred beats make a 3-minute cut)

| Beat | Where | What it shows |
|---|---|---|
| 1 ★ Opening | `/` | Three doors for missions |
| 2 Merchant asks | `/demo/soundbox`, **Request a callback** | A merchant-requested mission |
| 3 ★ Signals | `/missions`, **Load demo signals** | Data-driven missions, cards, priority queue |
| 4 ★ Phone call | phone + laptop `/call/<id>` | AI disclosure, worry meter, plan, sourced answers, consent, link through the safety gate |
| 5 ★ Verified done | phone: tap **Open the onboarding link** on the message card (or in the email), complete the mock page | DONE only when the onboarding system confirms |
| 6 ★ Knowing when to stop | **Run scenario**: Distressed merchant | Hand-off to a person with a context card, no writes |
| 7 Approval | **Run scenario**: Offline Soundbox, then the Approvals tab | The visit waits for a person's approval |
| 8 Win-back | **Run scenario**: Win-back, device problem | Listens, raises a ticket, no offer |
| 9 Coach | `/coach` | Suggests a human caller's next move |
| 10 Insights | `/insights` | Worries, funnel, hand-off reasons |
| 11 ★ Close | | Every business system is a labelled mock, not affiliated with Paytm |

### What to say on the phone (beat 4)

Use a Soundbox mission such as Sharma General Store. These lines were run through the tunnel against the live model:

1. "Haan ji, boliye?" Chanakya says it is an AI assistant first.
2. "Iska mahine ka kiraya kitna hai? Koi extra charge toh nahi katega?" The worry meter moves to charges; Chanakya
   points to official pricing and quotes no number.
3. Wait until Chanakya asks whether to send the link, then: "Haan ji, link bhej dijiye. Reminder bhi bhej dena."
   A plain "Yes" or "Haan ji" also works. A message card with the link appears under the call, and the email arrives
   if it is on. A yes said before it asks, or a bare "Haan", "Ok" or "Achha, theek hai", is correctly not taken as
   consent, and it asks again.
4. "Theek hai, dhanyavaad."

Do not offer an OTP in the sale call: Chanakya refuses and closes the mission as not interested. To show that refusal,
use a second mission.

### Logs and finding problems

With `DEMO_TOOLS_ENABLED=true` the backend writes its log to `.state/logs/backend.log` (rotated at 5 MB). **Save run
log** writes `.state/runs/<time>/`:

- `missions.json`: every mission with its full ledger
- `transcript.md`: each call as readable lines, with each move and action
- `report.md`: problems found in every called mission: no AI disclosure, a write without recorded consent, a reply
  slower than 4 seconds, rule breaks in Chanakya's lines (sensitive data asked, invented amounts, pressure, the em
  dash), Hinglish mixed with Devanagari in one reply, and ERROR or Traceback lines in the backend log since the last
  save. Blocked or pending actions and reply times are listed as notes.

`.state/` is ignored by git, so no transcripts or logs are committed.

### Rehearsal loop

1. Before each session: `./init.sh`, then `python scripts/demo/scenarios.py` (expect 6/6).
2. Run the demo once from a fresh ledger, then **Save run log**.
3. Read `report.md`, fix the cause, and repeat only the beat that failed (one scenario or one phone call).
4. Two clean full runs, then record the backup video (below).

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
