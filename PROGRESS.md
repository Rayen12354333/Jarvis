# Jarvis — Progress Log / Handoff

This file exists so any AI assistant (Claude, Codex, whatever) picking this
project up mid-stream has full context without needing the original chat
history. Update it after every meaningful change — new entry at the top of
the "Session log" section, plus keep "Current state" accurate.

Repo: https://github.com/Rayen12354333/Jarvis (the `jarvis.git` remote also
works, GitHub redirects it). Build plan / architecture rationale lives in
`PLAN.md` at repo root — read that first for the full picture, this file is
just the running diff on top of it.

---

## Current state (as of last update)

- **Current product direction:** `PRODUCT.md` is the current capability guide,
  audit, acceptance criteria, and development order. Product first; hand
  gestures later. This is a tested prototype upgrade, not a finished universal
  computer-control product.
- **Persistent Work Sessions:** implemented and live-Gemini tested with
  temporary storage. Explicit start/resume/list/read/save/export; sources,
  decisions, notes, and next steps persist locally in SQLite. Resume never
  creates a new session. Markdown exports preserve complete saved history.
- **Browser-native assistance:** Safari/Chrome current-page viewport context,
  URL navigation/history, and visible YouTube ordinal selection implemented.
  Fixed scripts, validated URLs, observed-tab guards, no auto permission changes.
  Target selection excludes ads/Shorts; playback checks exclude pre-roll ads.
- **Typed menu requests:** implemented with persistent follow-up context,
  cancellation, read-reply menu, execution receipts, and setup diagnostics.
  Voice must be stopped first; unifying input modes is still future work.
- **Execution reliability:** explicit completion, factual fast confirmations,
  duplicate-mutation guards, retained tool evidence, concurrent research,
  bounded cache freshness, verified media state, and screen focus/revoke checks.
- **Phase 0 (env setup):** done.
- **Phase 1 (wake word):** done. "hey jarvis" via openWakeWord, tuned and
  debounced.
- **Phase 2 (listen → transcribe → Gemini → speak):** done. Full loop works:
  say "hey jarvis", faster-whisper transcribes each utterance, one stateful
  Gemini chat handles the whole wake session, and Kokoro speaks each reply.
- **Multi-turn conversation:** done. One wake phrase opens a session. Jarvis
  gets a varied Gemini-generated greeting, waits up to 10 seconds for speech,
  and accepts direct follow-ups with full context. Gemini also generates varied
  conversational handoffs and interprets continue/wait/sleep intent in context.
- **Gemini is now the primary brain:** every real voice or `--text` utterance
  goes to Gemini 3.5 Flash-Lite. The regex router is no longer in the live path;
  it remains only as legacy scaffolding for future deterministic tools.
- **GroqCloud second brain:** done. A valid `gsk_` GroqCloud key enables
  `openai/gpt-oss-120b` for explicit second opinions and difficult reasoning.
  Gemini evaluates its advisory answer and speaks one synthesis. If Gemini
  fails, the second provider offers answer-only conversation fallback without
  receiving or controlling Jarvis's local-action schema.
- **Web research:** done. Gemini can request focused searches, inspect the
  results, select authoritative public pages to read, and synthesize a grounded
  spoken answer. Search/page source links are printed in Terminal. The web layer
  is keyless and blocks private/local addresses.
- **Live clock and timers:** done. Exact time/date comes from the local clock at
  execution time. Multiple named countdowns use monotonic deadlines and ring
  while Jarvis is in conversation or passively waiting for the wake phrase.
- **Phase 3 media control:** volume get/up/down/set/mute/unmute is done through
  validated Gemini-callable macOS actions. Spotify-native playback controls are
  done; system-wide playback control for other media players remains.
- **App control foundation:** done. Jarvis can safely resolve and open installed
  apps, search Spotify/YouTube/the browser, and chain app actions through Gemini.
- **Named Spotify playback:** done. "Play [song]" resolves a validated Spotify
  track URI and starts it instead of stopping at the search-results page.
- **Apple Notes creation:** done. Jarvis writes a title/body into the default
  Notes folder and only confirms after Notes returns the created item's ID.
- **Time-limited screen vision:** explicit sessions last 5 seconds–30 minutes
  (30-minute default). Shared voice/menu consent, click-through cyan main-display
  tint, live countdown, menu/voice revoke, shutdown revoke, and expiry implemented.
  Each request while enabled includes a fresh compressed main-display image;
  old image parts are removed from subsequent Gemini chat history.
  Temporary PNGs are deleted locally. During a session Jarvis can also scroll
  the active app or single-click a visible target after a fresh inspection.
  Real use requires Screen Recording and Accessibility permissions for the app
  launching Jarvis.
- **Speaker bleed protection:** done. Mac output is temporarily muted only while
  Jarvis records the user's request, then its prior state is restored.
- **Phase 4 menu bar:** start/stop/status/log access and start-at-login implemented.
  It now displays live Listening/Transcribing/Thinking/action/Speaking activity
  beside the icon. Log rotation remains; Gmail, SUIS briefing, and later extras
  are not started.

### Key config (`.env`, gitignored — not in the repo, this is what's set locally)
```
WAKE_WORD_MODEL=hey_jarvis
WAKE_THRESHOLD=0.75          # bumped from 0.5, see session log
SPEECH_START_TIMEOUT_S=10.0  # time allowed to begin speaking
SILENCE_TIMEOUT_S=0.9        # faster end-of-utterance detection
MAX_RECORDING_S=15.0         # cap after speech begins
WHISPER_MODEL=base.en
WHISPER_COMPUTE_TYPE=int8
VOICE_NAME=am_adam           # Kokoro voice id (American male)
VOICE_SPEED=1.0              # normal speed for now, will revisit later
GEMINI_API_KEY=              # configured locally; never commit the value
GEMINI_MODEL=gemini-3.5-flash-lite
GROQ_API_KEY=                # configured locally; never commit the value
GROQ_MODEL=openai/gpt-oss-120b
```

### Stack decisions that differ from the original PLAN.md write-up
- **Wake word:** openWakeWord, not Porcupine. Picovoice (Porcupine) killed its
  free/non-commercial tier — see PLAN.md section 2 for the full writeup.
- **TTS:** Kokoro-82M via `kokoro-mlx`, not macOS `say`. Free, local,
  Apple-Silicon-native, far more natural than the built-in `say` voices.
  Kokoro now generates the waveform without opening its own PortAudio output
  stream; Jarvis writes a click-faded temporary WAV and plays it through macOS
  `afplay`, avoiding mixed-rate CoreAudio crackle during replies.
  Voice picked: `am_adam`. Other voices tested: `bm_daniel`, `bm_fable`,
  `bm_george`, `bm_lewis` (British male options, none picked yet — revisit
  later if `am_adam` gets old). Kokoro also supports a `speed` multiplier;
  user wants a faster/"spicier" delivery eventually but that's deferred —
  Kokoro has no tone/emotion knob, so "spicy" will have to come from how
  handler reply text is written (short, punchy lines) rather than a model
  setting.

### Known issues / open items
- **Accessibility remains denied for the diagnostic launcher.** Live read-only
  check showed Microphone and Screen Recording allowed, Accessibility denied.
  Generic clicks/scrolls still need the appropriate launcher's permission.
  A signed app bundle with stable onboarding is not implemented.
- **Not fully live UI/voice tested in this upgrade.** The computer-use inspector
  timed out. The reloaded menu process stayed alive and startup log was empty
  (no exception), but this does not establish a full click-through UI test.
  Safari/Chrome script compilation and deterministic DOM fixtures passed;
  real video playback and microphone-to-speaker latency still need manual tests.
- **Browser limits:** foreground Safari/Chrome only, viewport text, standard
  YouTube videos only, browser JavaScript-from-Apple-Events permission required.
  Safari tab indices are less robust than Chrome stable tab IDs. Screenshot
  PID guards do not detect every same-app window/tab/layout change.
- **Prototype privacy/security:** private local files are not encrypted at the
  application layer; requested context goes to cloud models. Legacy voice logs
  may include utterances. Prompt restrictions do not independently verify the
  safety of every generic screen target. No high-impact unattended use.
- **Timers are process-lifetime only.** They survive conversation sleep but not
  quitting Jarvis or rebooting the Mac. Persistence belongs with the Phase 4
  always-running/menu-bar work.
- A timer that expires while a Gemini/web/TTS operation is already blocking is
  announced as soon as that operation returns. It interrupts passive listening
  and the pre-speech wait to stay timely in the normal case.
- **Wake word false-accepts on phonetically similar phrases.** Saying "hey
  travis" scored as high as 0.998 on the "hey_jarvis" model — same range as
  genuine hits — so raising `WAKE_THRESHOLD` (done: 0.5 → 0.75) helps the
  common case but does not reliably reject this. Not fixed at the model
  level. If it becomes a real nuisance: add a second gate after STT that
  checks whether the transcribed wake phrase actually resembles "jarvis" and
  silently drops the utterance if not (cheap since STT already ran on every
  detection).
- **Phase 1's full false-positive checkpoint** (PLAN.md: <~2 false fires/hour
  over a normal working day) has only been spot-checked in short bursts, not
  run for a full passive hour. Worth doing once Phase 3 is further along.
- Voice speed/personality tuning deferred — currently normal speed, plain
  handler text (e.g. "It's {time}."). Revisit once more handlers exist and
  the "personality" of replies matters more.

---

## Session log (newest first)

### perf(screen): lean visual turns, visible 30-minute consent, verified browser scroll

The user's actual test log showed a 28.05-second visual/ad request before speech,
plus 6.16 seconds of spoken output. Later model requests reached 6–8 seconds
each after multi-megabyte screenshots accumulated in history. Generic scrolling
claimed movement based only on sending a wheel event.

Changes:

- Screenshot uploads now preserve aspect ratio at a 1600-pixel longest edge,
  JPEG quality 85. Processed image parts are replaced with textual markers using
  the SDK's public chat-history API; text/tool findings remain available.
- An explicitly enabled session supplies a fresh image with the first model
  request, avoiding an image-discovery round trip. Follow-ups never automatically
  renew access. Default/max access is 30 minutes.
- New `screen_access.py` atomically shares expiring consent between voice/menu;
  dead owner PIDs, corrupt grants, revoke, and expiry fail closed. New
  `screen_overlay.py` displays a click-through cyan main-display tint without
  taking keyboard focus. Menu provides enable confirmation, countdown, and
  stop. Indicator failure revokes the shared grant.
- Exact voice privacy commands revoke locally before capture/model calls.
  Voice exit, conversation sleep, menu Stop and Quit also revoke. Voice
  interruption during processing/speech is still not implemented: use the menu.
- Native browser scroll handles top/bottom and verifies position/boundaries.
  Generic wheel events no longer claim observed movement. Dedicated YouTube
  play/pause/Skip Ad controls prevent Spotify misrouting. Searches stay in the
  requested browser or open a visible supported browser from another app.
- Prompt requests short routine replies; trusted confirmations are concise.
  Kokoro warm-up synthesizes a short phrase silently. Long replies are split
  into sentence/word-bounded chunks so first playback starts before later
  chunks are synthesized. This is chunked speech, not full streaming/barge-in.

Verification on 2026-09-06:

- **237 offline tests pass**, Ruff passes. Includes the actual fixed scroll JS
  in a headless fixture, cross-process revoke, expiry, owner death, indicator
  failure, close ordering, no-focus click-through window contract, image-history
  cleanup, and first-image one-call visual targeting.
- `tests/performance_smoke.py --live --tts`: four Gemini requests with a
  generated number image succeeded in **1.93 / 1.36 / 1.39 / 1.42 seconds**;
  **zero image bytes retained** in subsequent chat history each time.
- Local Kokoro first warm-up **5.91 seconds**; warmed synthesis **0.22 / 0.17
  seconds** for two short confirmations. No audio was played. These numbers
  exclude microphone input, actual screen capture, real UI actions, and network
  variability under sustained use; they are not end-to-end product guarantees.
- Native UI inspection timed out after 10 seconds. The tint's appearance and
  real browser/voice behavior still need a manual acceptance pass. No real
  screenshots were captured by this verification and access remains opt-in.
- Stopped the confirmed resting voice process and reloaded the existing menu
  LaunchAgent. New menu process started without log errors; voice is stopped
  until the user selects Start Jarvis, and screen access remains off.

### feat(product): work sessions, browser controls, typed menu, verified execution

Implemented the first product-focused upgrade after the request for a practical,
fast, smart assistant. `PRODUCT.md` contains the full analysis, concrete user
flows, remaining capability limits, release gates, and deferred hand-gesture plan.

New modules: `workspaces.py` (private SQLite and unique Markdown exports),
`browser.py` (bounded Safari/Chrome operations), `commands.py` (serial typed
conversation worker), `diagnostics.py` (read-only checks). Actions and model
schema/prompt now expose these capabilities. Menu adds typed requests, cancellation,
reply view, recent evidence, setup, guide, and export-folder access. Modal input
restores the previously observed app before execution; replies do not steal focus.

Fixed premature action completion and pre-action spoken success claims. Gemini
uses explicit `task_complete`; recognized controller evidence alone may use the
one-call fast path. Tool results survive into follow-ups, internal evidence is
not sent to stateless fallback, and repeated mutations are guarded within a
request. Gemini transport uses a 25-second timeout and one transport attempt;
tool workflows have eight rounds. These are per-stage bounds, not a whole-task
latency guarantee. Independent searches/page reads run concurrently; caches
expire after 60 seconds / 300 seconds, with bounded storage.

System/Spotify volume writes now read back the actual level. Spotify only claims
named playback after matching playing state and requested URI; unverified
commands are not automatically retried. Screen captures reject revoked/expired
authorization and app switches; clicks consume one fresh observation and check
the foreground PID. Menu Stop sends SIGTERM which now unwinds the voice volume
guard and speech cleanup instead of bypassing finally blocks.

Verification:

- **213 offline tests pass**, Ruff passes, and `git diff --check` passes.
- Browser agent compiled 17 Safari/Chrome AppleScript variants and all fixed
  JavaScript programs without executing them against user tabs. DOM fixtures
  exercise visible ordering/exclusions and playback/ad state.
- **Four live Gemini workflow checks pass** using synthetic data and simulated
  Mac/browser actions, with real temporary SQLite/export files:
  single Spotify volume routing 1.50s; start/save/export 2.82s; resume across
  fresh model conversations 2.64s; page-to-saved-source summary 4.31s.
- These timings exclude microphone capture, transcription, synthesis/playback,
  real app launch latency, and live webpage retrieval. They are a single smoke
  run, not statistical product latency claims.
- The initial live run caught a resume-name error. Added `resume_workspace`
  existing-only semantics and explicit full-name/list guidance; rerun passed.
- Reproducible opt-in command:
  `PYTHONPATH=. .venv/bin/python tests/live_smoke.py --live`.
- Read-only system diagnostic: Gemini/Groq keys configured, microphone and
  screen recording allowed, Accessibility denied for this launcher. No keys
  printed and `.env` remains Git-ignored.
- Reloaded the existing `com.rayen.jarvis-menubar` login job with voice stopped.
  Replacement process confirmed running with no startup errors. Visual menu
  inspection timed out, so manual UI/voice/real-browser checks remain open.

No hand tracking, billing, account integrations, publishing, or repository commit
was performed. Existing dirty changes were preserved. No real music playback,
screen capture, or volume mutation was used by the live smoke tests.

### perf(voice): one-call actions, background warm-up, and visible activity

Measured the live menu-bar logs and found three avoidable latency sources:
1.5 seconds of end-of-speech silence, lazy Whisper/Kokoro initialization after
listener restarts, and a second Gemini request after every successful local
action solely to phrase its confirmation. Visual targeting paid a third request
after clicking.

Reduced end-of-utterance silence to 0.9 seconds while preserving the full
10-second speech-start window. Whisper and Kokoro now warm in the background and
prefer already-cached snapshots without remote revision checks. Successful
local actions finish from their trusted result or Gemini's held confirmation,
cutting normal actions from two model calls to one and visible locate-and-click
from three calls to two. Failed actions still return to Gemini so it can recover.

Added an atomic cross-process activity channel. The menu-bar item now exposes
Listening, Transcribing, Thinking, Looking at screen, specific action, and
Speaking states; fast action names remain visible for two seconds. A real Gemini
dry run routed and completed simulated scrolling in one request and 1.62 seconds.
An isolated cached Whisper/Kokoro warm-up completed in 1.45 seconds without
using the microphone or playing audio.

### feat(screen): guarded scrolling and fresh-vision clicking

Added `scroll_screen` and `click_screen` to the allow-listed Gemini action
schema. Jarvis can now scroll the currently active app, or inspect a fresh
screenshot, locate the center of a user-requested visible target such as the
second video, and issue one primary click using 0-1000 normalized coordinates.
Normalized coordinates avoid screenshot-pixel versus Retina-point drift.

Screen control retains the existing 5-second to 10-minute authorization window.
Clicks additionally require an inspection no more than 15 seconds old; each
screenshot permits one click, and scrolling invalidates it. The prompt forbids
visual clicks for typing, purchases, account changes, sending, deletion, or
permission dialogs, and on-screen text remains evidence rather than authority.
macOS Accessibility permission is checked before posting Quartz input events.

### feat(menu-bar): launch-at-login Jarvis controller with custom icon
Converted the supplied five-bar mark into a genuine transparent RGBA PNG using
the built-in image editing workflow, retained the high-resolution source, and
created a cropped 40×40 Retina template icon. The project copies live at
`assets/jarvis-menu-source.png` and `assets/jarvis-menu-icon@2x.png`; template
mode lets macOS tint the black mark correctly on light and dark menu bars.

Added a `rumps` controller with live status plus **Start Jarvis**, **Stop Jarvis**,
**Open Jarvis Log**, and **Quit Jarvis Menu Bar**. The start action executes the
project's virtualenv Python directly with `-m jarvis.main`, so it never needs
shell activation. Stop terminates only the voice process owned by the controller,
while Quit stops that process and removes the status item.

Installed and validated the per-user LaunchAgent at
`~/Library/LaunchAgents/com.rayen.jarvis-menubar.plist`. It runs the controller
at login in the Aqua GUI session; `launchctl` reports the current job as running.
Added hardware-free subprocess and plist tests. All 60 tests, Ruff, compilation,
and diff checks pass.

### feat(llm): add a GroqCloud-hosted 120B second brain
The provided `gsk_` credential was correctly identified as a GroqCloud key—not
an xAI Grok key—and stored only in gitignored `.env`. Its live Models endpoint
returned HTTP 200, exposed 14 models, and confirmed access to the configured
production model `openai/gpt-oss-120b`.

Added `GroqProvider` over Groq's OpenAI-compatible HTTP API. Gemini remains the
stateful controller and may request one standalone `specialist_query` when the
user says "ask Groq/Grok," "double-check," requests a second opinion, or poses
a genuinely difficult reasoning task. The 120B response returns to Gemini as
advisory evidence, and Gemini resolves it into one concise spoken answer. A live
dual-model calculation successfully followed Gemini → GPT-OSS 120B → Gemini and
returned 5,781.

If Gemini fails, GroqCloud provides stateful spoken-answer and continue/wait/
sleep fallback. For privacy and control separation, that fallback receives a
minimal prompt and schema, not Gemini's full Jarvis prompt or any Mac-action
schema, and it cannot operate the computer. Standalone live specialist and
minimal fallback calls both passed. Groq strict-schema normalization is covered
alongside provider history, synthesis, and failure takeover; all 57 tests and
Ruff pass.

### fix(spotify): control Spotify's own volume
Added `adjust_spotify_volume` and `set_spotify_volume` as explicit Gemini-callable
actions. They read and set Spotify's native `sound volume` property from 0–100,
clamp relative adjustments, refuse invalid levels, and leave the Mac's master
output unchanged. The prompt now clearly distinguishes "lower Spotify" from an
ordinary system-volume request. All 50 tests and Ruff pass.

### fix(speak, games): stable CoreAudio playback and direct computer-game advice
Kokoro no longer opens its default `sounddevice` output stream. It generates a
waveform, Jarvis clamps it safely, adds an 8 ms edge fade to prevent clicks,
writes a temporary 24 kHz PCM WAV, and plays that file through macOS `afplay`.
The file is always deleted afterward. This keeps speech output on one stable
CoreAudio path while the microphone is stopped, addressing the new strange
sound heard during replies as well as the earlier mixed-rate crackle.

Removed Jarvis's custom game refusal from the Gemini system prompt. For chess
and other games—especially computer opponents, puzzles, and practice—Jarvis now
leads with the strongest move/action and a short reason, with no fair-play or
ethics lecture. Screen inspection remains explicit, time-limited, and on demand.

Ruff, compilation, diff checks, and all 47 tests pass. A real Kokoro generation
and `afplay` round trip also completed successfully through the Mac speakers.

### feat(screen): privacy-gated, time-limited Gemini vision
Added `ScreenVisionManager` and four structured actions:
`start_screen_vision`, `inspect_screen`, `screen_vision_status`, and
`stop_screen_vision`. A user must explicitly request screen help; authorization
defaults to two minutes and is hard-bounded from 5 seconds to 10 minutes. It
expires by monotonic clock and can be revoked immediately. While active, the
voice session remains patient through silent listening windows.

`inspect_screen` runs macOS `screencapture` for the main display, caps the PNG at
20 MB, reads it into memory, and deletes the temporary file in `finally`. The
image is attached to the same Gemini chat as a multimodal part. System and tool
prompts label screenshot pixels/text as untrusted evidence, prohibit following
on-screen prompt injections, restrict analysis to the requested purpose, and
avoid unrelated sensitive content. Chess and other game questions receive a
direct recommended move and short explanation, particularly against a computer,
in puzzles, or during practice. This version does not continuously record or
capture system audio.

There are 43 passing tests after the screen work, and Ruff passes. Tests cover
authorization-before-capture, automatic expiry, maximum duration, explicit
revocation, temporary-file deletion, and attaching image bytes to Gemini only
after authorization. A live synthetic-image test succeeded: Gemini identified
a bundled flower photo after selecting start + inspect actions, with a 30-second
session active. A real local `screencapture` attempt returned "could not create
image from display" because the launcher lacks macOS Screen Recording permission.
The correct System Settings privacy page was opened for the user; permission and
a real-screen retest remain.

### fix(notes): create and verify notes instead of pretending
The user found that Jarvis said it created a note when it had only opened the
Notes app. That was a real capability/confirmation bug: no create-note action
existed, and Gemini overclaimed what `open_application` had accomplished.

Added a dedicated `create_note` action backed by Apple Notes' native scripting
dictionary. The tool targets the default account and folder, supplies a title
and HTML-escaped body as separate `osascript` arguments rather than executable
source, shows the created note, and requires a non-empty unique note ID before
returning success. Gemini is explicitly forbidden from treating app launch as
create/type/edit/save/send/delete and must admit when no matching local action
exists. Local action results are now printed in Terminal for diagnosis.

All 39 tests and Ruff pass. The AppleScript compiled successfully outside the
Codex sandbox. A live Gemini check used `create_note("Shopping", "buy milk and
coffee")` rather than open-only. Two temporary end-to-end notes were created,
read back by returned ID, and immediately deleted; the second verified the final
format contains one title followed by the requested body.

### fix(spotify): resolve and immediately play named tracks
Added `play_spotify_track` as a distinct structured action so Gemini no longer
maps "play God's Plan" to the display-only `search_in_app` action. The local
resolver runs a focused public track lookup, ignores every result outside the
exact HTTPS `open.spotify.com` host and `/track/<22-character base62 ID>` path,
converts the accepted ID into a Spotify URI, and calls the installed client's
native `play track` command. Search-result text is logged but not returned to
Gemini as trusted instructions.

Added resolver, domain/path rejection, fixed AppleScript, and action delegation
tests. All 35 tests and Ruff pass. A live non-playing check resolved God's Plan
to track `6DCZcSspjsKoFjzjrWoCdn`; a separate live Gemini test with a fake app
controller chose `play_spotify_track("God's Plan Drake")` and never invoked the
old search action. Actual playback was left for the user's voice test.

### feat(apps): installed-app launching, searches, and Spotify playback
Added `MacAppController`, which discovers real `.app` bundles under the system
and user application directories before launching a requested app. Model text
is never interpolated into a shell command. It can open any unambiguously
installed app and provides validated search destinations for Spotify, YouTube,
and the default browser.

Spotify's installed scripting dictionary confirmed native play, pause,
play-pause, next, previous, current-track, state, and volume support. Exposed
playback and now-playing as structured Gemini actions with fixed AppleScript
commands. Spotify searches use its application URI and launch the installed
client. Named-result autoplay was added in the following fix; personal account
and playlist data still require a later OAuth integration.

Added app resolution, unknown-app rejection, URI encoding, fixed-command, and
action-delegation tests. All 30 tests and Ruff pass. A live Gemini decision test
with a fake controller correctly requested `open_application(Spotify)` followed
by `control_spotify(play)` and waited for both results before confirming, without
opening or changing the real app during the test.

### fix(audio): keep playing videos out of recorded requests
Video and podcast speech could cross from the Mac speakers into the built-in
microphone and trip the same speech detector as the user. Added a listening
volume guard: after Jarvis gives its greeting, macOS output is temporarily
muted, the last room sound is allowed to decay, and queued pre-mute microphone
frames are discarded. The exact prior mute state is restored before Whisper,
Gemini, any volume action, or Jarvis's reply runs, so "lower the volume" still
uses the real pre-listening level. Existing user mutes are preserved.

The behavior defaults on and can be disabled with
`MUTE_OUTPUT_WHILE_LISTENING=false`. Added restoration, existing-mute, and mic
queue tests. All 25 tests and Ruff pass. A live round-trip verified the Mac went
from unmuted to muted and back while leaving its volume level unchanged.

### feat(actions): live clock, monotonic timers, and macOS volume control
Added a bounded local-action schema to Gemini's structured turns. Gemini can
request the exact current date/time, create/list/cancel multiple named timers,
inspect output volume, adjust or set it from 0–100, and mute/unmute. Python
validates every argument and executes a fixed allow-list; Gemini receives the
real result before it is allowed to claim success. No arbitrary command string
from the model is executed.

Countdown deadlines use `time.monotonic`, so wall-clock corrections do not make
them jump. The timer manager persists across wake sessions for as long as the
Jarvis process runs. Due alarms interrupt passive wake listening and the
10-second pre-speech window; once the user has started talking, Jarvis preserves
the utterance and announces the alarm immediately afterward. Added deterministic
timer, recorder-interruption, volume-validation, and Gemini orchestration tests.
All 22 offline tests and Ruff pass. Live checks confirmed a one-second timer,
the macOS volume read without changing it, and Gemini invoking
`get_current_time` before giving its answer.

### feat(web): Gemini-directed keyless web research
Connected the stateful conversation to a free local research loop. Gemini can
return up to three focused `web_queries`; Jarvis executes them through `ddgs`
and sends the result titles, URLs, and snippets back into the same chat. Gemini
then selects up to two `read_urls`, and Jarvis downloads bounded public HTML or
plain-text pages, removes scripts/navigation, and returns readable evidence for
the final synthesis. Sources are printed as `[web]` lines in Terminal.

The orchestrator refuses to accept a snippet-only answer after Gemini requests
a search: it requires at least one source page to be opened before returning the
final speech. Research is capped at four tool rounds and five results per query.
Page downloads are capped at 1 MB / 12,000 extracted characters, follow at most
four redirects, accept only public HTTP(S), and reject local/private IP targets
to reduce SSRF risk. Web text is explicitly labeled untrusted in both tool output
and Gemini's system instruction.

Google's native Search grounding was tested first but returned
`429 RESOURCE_EXHAUSTED`: current Gemini 3 API pricing makes Search unavailable
on the free tier without enabling billing. To preserve the project's free-first
policy, added `ddgs`, `httpx`, and `lxml` instead. Live validation searched for
the current Python release, printed five sources, opened Python.org, and returned
the verified `3.14.7` answer. Added offline search formatting, HTML extraction,
private-address blocking, and research-orchestration tests.

### refactor(llm): make Gemini the stateful conversational brain
Replaced the handler-first / Gemini-fallback live path with one stateful Gemini
chat per wake session. Every utterance now reaches Gemini, so follow-ups keep
the full conversation history instead of being treated as isolated commands.
`--text` mode also goes directly to Gemini.

Gemini returns a structured `AgentTurn` containing natural spoken text and one
of three local transitions: `continue`, `wait`, or `sleep`. That lets the model
interpret short answers from context: "yes" can accept an offered follow-up,
while "yes, that's all" ends the session. A `wait` transition makes the audio
loop remain open across unlimited silent windows; a `sleep` transition returns
to passive wake-word listening. API failure remains safe and ends only the
active session.

Greetings and post-answer handoffs are now generated by Gemini. Greeting style
is varied per wake session, the prompt tells Jarvis not to repeat stock phrases,
and the voice persona is concise, conversational, occasionally uses "sir", and
avoids markdown because the output is spoken. The SDK now uses `Chat.send_message`
with structured Pydantic output, eliminating the old isolated-call AFC warning.
Live validation confirmed a varied greeting, memory of a fact across a follow-up,
and a natural context-aware sign-off.

### feat(conversation): greet, wait for speech, and support follow-ups
Reworked the one-command-per-wake loop into a conversational session. After
"hey jarvis", Jarvis now says "Hello, sir. How can I help you?" and waits up
to 10 seconds for speech to start. Starting-speech timeout is separate from
end-of-utterance silence, so the wait does not add dead air to Whisper input.
The recorder now allows 1.5 seconds of mid/end silence and up to 15 seconds of
speech, with a short pre-roll to avoid clipping the first syllable.

After each answer, Jarvis asks "Is that it for now, sir?" A direct question is
handled as a follow-up without another wake phrase. "Yes" and "rest for now"
close only the active conversation and return to passive wake listening.
"Wait", "no", or "not yet" enables patient mode, which keeps listening across
empty 10-second windows until the user explicitly ends the session. Mic queues
are cleared after TTS restarts to prevent stale audio becoming the next reply.
Added hardware-free recorder and conversation tests.

### feat(llm): add Gemini fallback layer for unmatched commands
Added an LLM layer so Jarvis isn't limited to the fixed regex handlers in
`handlers/*.py` -- when `router.dispatch()` finds no matching handler, it
now calls out to an LLM instead of just logging "matched no handler" and
doing nothing.

**Model/provider decision:** compared Claude Haiku ($1/$5 per M input/output
tokens), OpenAI GPT-5 Nano ($0.20/$1.25), and Google Gemini 2.5 Flash-Lite
($0.10/$0.40, AND a genuine free tier -- 1500 requests/day, no credit card,
via aistudio.google.com/apikey). Went with Gemini: free tier comfortably
covers Jarvis's realistic fallback volume (10-50 requests/day), consistent
with the project's running "avoid paid signups where possible" pattern
(openWakeWord over Porcupine, Kokoro over paid TTS). Traded off: Google may
use free-tier prompts for training, no uptime SLA -- acceptable for a
personal assistant with no sensitive data flowing through it. If Gemini's
answers feel insufficient later, user may switch to Claude (~$1-2/month
estimated for this usage pattern) -- see git history/chat for that cost
comparison if resurrecting the decision.

**What changed:**
- `jarvis/llm.py` (new) -- lazy-loaded Gemini client (`google-genai` SDK),
  `ask_llm(text)` sends the transcribed utterance with a short system
  prompt ("Jarvis, 1-2 sentences, no markdown -- gets spoken via TTS") and
  returns the reply, or `None` on any failure (never crashes the voice
  loop on a bad API call).
- `jarvis/router.py` -- `dispatch()` now imports and calls `ask_llm()` as
  the last step instead of returning `None` when nothing matches. Import is
  local to that branch so `google-genai` isn't a hard dependency for
  anything that doesn't hit the fallback path.
- `jarvis/config.py` / `.env.example` / `.env` -- added `GEMINI_API_KEY`
  (blank until user pastes a real one) and `GEMINI_MODEL` (now
  `gemini-3.5-flash-lite`; the former 2.5 model was retired for new users).
- `requirements.txt` -- added `google-genai`.

**Validated:** text-mode and full voice-mode calls both returned HTTP 200 and
produced spoken Gemini replies using `gemini-3.5-flash-lite`.

### fix(main): pause mic stream while Jarvis speaks — commit `7f89a7c`
Real-world testing surfaced audible crackling during Kokoro's replies. Root
cause: the mic's input stream (16kHz) stayed running while Kokoro opened a
separate output stream (24kHz) to play the reply — on a MacBook, built-in
mic and speakers share the same CoreAudio device/clock, so both streams
active at once caused buffer glitches heard as crackle over the voice. Fix:
`main.py`'s `run_voice_loop` now calls `mic.stop()` right before `speak(...,
blocking=True)` and `mic.start()` right after. This also happens to close
the Phase 1 "Jarvis can hear its own voice and re-trigger" risk that
`speak.py`'s docstring had flagged but left unwired.

### feat(speak): switch TTS backend from macOS `say` to Kokoro-82M — commit `7db9d0c`
Replaced `speak.py`'s `say` subprocess call with `kokoro-mlx` (local, free,
Apple-Silicon-native neural TTS, no signup/API key — same philosophy as
choosing openWakeWord over Porcupine). Lazy-loads the `KokoroTTS` model on
first use so importing `jarvis.speak` doesn't force a model load. Added
`VOICE_NAME` (voice id, e.g. `am_adam`) and `VOICE_SPEED` (>1 faster, <1
slower) to `config.py`/`.env`. Both are overridable per-call.
Tested voices before picking: `am_adam` (chosen), `bm_daniel`, `bm_fable`,
`bm_george`, `bm_lewis`. Speed tested up to 1.45x but staying at 1.0 for now.
Also considered/rejected: macOS Enhanced/Premium system voices (via
Accessibility → Read & Speak) as a lower-effort alternative — user already
liked Samantha's quality well enough that it wasn't worth the download hunt
once Kokoro was on the table.

### feat(speak): add VOICE_NAME config for picking a macOS TTS voice — commit `50d86d9`
(Superseded by the Kokoro switch above, but left in git history.) Added a
`VOICE_NAME` config so `say` calls could use a chosen system voice instead
of always the default. Same commit also bumped local `.env`'s
`WAKE_THRESHOLD` 0.5 → 0.75 after Phase 1 testing showed some false accepts
on phonetically similar phrases ("hey travis") scoring in the 0.5-0.9 range.

### fix(wake): reset openWakeWord model state after each detection — commit `82af5f9`
Real-world testing showed bursts of several "wake word detected" log lines
firing within ~100ms of each other from a single spoken "hey jarvis" — most
of the extra detections recorded near-silent clips with no transcription,
i.e. not separate utterances. Root cause: `openwakeword.model.Model` keeps a
rolling `prediction_buffer` per wakeword across `predict()` calls (its own
patience/smoothing logic), and nothing was clearing it. Residual state from
the tail of the utterance that just triggered detection could immediately
re-trigger another one before any new speech happened. Fix: call
`wake_model.reset()` right after each detection, before recording starts.

### docs: fix stale Porcupine/Picovoice references — commit `2d0ff2e`
`README.md`/`PLAN.md` still described the wake phrase as bare "Jarvis" and
referenced Porcupine in checkpoint/requirement sections despite the actual
code (and the "Correction, Sept 2026" sections) having already switched to
openWakeWord/"hey jarvis". Also found the local `.env` (gitignored, so it
never got updated when `.env.example` did) still had dead
`WAKE_WORD`/`WAKE_SENSITIVITY`/`PICOVOICE_ACCESS_KEY` vars that
`config.py` never reads — meaning any attempt to tune wake-word threshold
via `.env` was silently doing nothing. Fixed both.

### phase1: audible beep + persistent log line on wake-word detection — commit `219dd6a`
### fix(wake): pin openWakeWord to a GitHub commit, not the stale PyPI release — commit `f14411c`
### fix(wake): replace Porcupine with openWakeWord — commit `0f7bc99`
### phase0: scaffold project structure per PLAN.md — commit `c8b9049`
Earlier history — see PLAN.md section 2 for the Porcupine → openWakeWord
rationale in full (Picovoice discontinued its free/non-commercial tier).

---

## Next step

Finish Phase 3 media control:
- Play/pause/next/previous via system-defined media key events (pyobjc), so it
  drives whatever app is actually playing rather than one hardcoded app.
- Keep those operations in the validated local-action layer in `actions.py`;
  the legacy `handlers/media.py` stub is not part of the live Gemini path.
