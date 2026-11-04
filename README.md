# Jarvis

A voice- and text-operated assistant for macOS: wake word, system/media control,
source research, browser assistance, and persistent work sessions.
Wake word, speech-to-text, and
text-to-speech run on-device; Gemini provides the primary conversational
intelligence. An optional GPT-OSS 120B model hosted by GroqCloud supplies
second opinions and answer-only fallback. For current information and research,
Gemini can direct a keyless local web search and read selected public source
pages before answering.

The full design doc, phase-by-phase plan, and the reasoning behind every
decision and the later architecture corrections lives in **[PLAN.md](./PLAN.md)**.

**Status:** Stateful voice conversation, live web research, real timers, exact
local time, macOS volume control, app launching/search, Spotify playback,
verified Apple Notes creation, time-limited Gemini screen vision, and selective
Gemini + GroqCloud dual-model reasoning are working. A login-launched menu-bar
controller starts and stops the listener without Terminal or virtualenv commands.

The current product guide, capability boundaries, and development priorities
are in [PRODUCT.md](./PRODUCT.md). Email and academic-service integrations
remain planned, not implemented.

## Quickstart

```bash
# 1. System dependencies (macOS, Homebrew). Skip xcode-select if already installed.
xcode-select --install
brew install python@3.11 portaudio ffmpeg

# 2. Virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Secrets
cp .env.example .env
# openWakeWord needs no key. Gemini is the primary conversation provider.
# GEMINI_API_KEY=your_key_from_aistudio_google_com
# Optional: a GroqCloud gsk_ key enables GPT-OSS 120B second opinions/fallback.
# GROQ_API_KEY=your_key_from_console_groq_com
# Fill in GOOGLE_OAUTH_CLIENT_SECRET_PATH / SUIS_* later, for Phase 5/6 only.

# 4. Phase 0 checkpoint
python tests/audio_check.py
```

macOS will ask for Microphone / Accessibility / Automation permissions the
first time you run something that needs the mic or system control. Grant
these to **whatever process actually runs the script** — if you run it from
VS Code's integrated terminal, VS Code needs the permission, not Terminal.app
(macOS grants permissions to the parent process). See PLAN.md, Phase 0.

## Running it

The normal daily control is the transparent five-bar **Jarvis menu-bar icon**.
It launches automatically when you sign in and offers:

- **Start Jarvis** — begin listening for “Hey Jarvis.”
- **Stop Jarvis** — kill the voice listener but keep the menu available.
- **Enable Screen Assistance (30 min)** — confirm temporary screen access;
  a click-through cyan tint and menu countdown show when it is on.
- **Stop Screen Assistance** — revoke screen access even while a request is busy.
- **Type a Request** — ask or follow up without speech; stop voice first.
- **Read New Reply** — read the typed answer and measured response time.
- **Cancel Typed Request** — prevent further actions after the in-flight step returns.
- **Recent Actions** — inspect actual tool results and execution times.
- **Setup & Permissions** — read-only diagnostics, without displaying API keys.
- **Open Exported Work Sessions** — reveal saved Markdown handoffs.
- **What Can Jarvis Do?** — open the product guide.
- **Open Jarvis Log** — inspect listener startup or permission failures.
- **Quit Jarvis Menu Bar** — stop the listener and remove the icon until the
  next login.

The login item directly runs this project's `.venv/bin/python`, so no shell
activation is involved. Its plist is installed at
`~/Library/LaunchAgents/com.rayen.jarvis-menubar.plist`. The commands below are
still useful for development and diagnostics, but are not needed for daily use.

While a request is active, short live labels appear beside the menu-bar icon:
**Listening**, **Transcribing**, **Thinking**, **Looking at screen**, the current
local action, and **Speaking**. Action labels remain visible long enough to be
noticed even when the operation itself finishes instantly.

```bash
# Full voice loop
python -m jarvis.main

# Skip the mic and send one prompt directly to Gemini
python -m jarvis.main --text "what time is it"

# Print only, without speaking
python -m jarvis.main --text "what time is it" --silent

# Force a sourced web-research test
python -m jarvis.main --text "research the latest Python release and verify it"

# Ask the live local clock without opening the microphone
python -m jarvis.main --text "what is the exact time right now"

# Explicitly consult the second model, then let Gemini unify the answer
python -m jarvis.main --text "ask Groq to solve this independently: 123 times 47"
```

Say **"hey jarvis"** -- that's the exact phrase openWakeWord's pretrained model
listens for, not just "jarvis". Jarvis asks Gemini for a fresh greeting, then
gives you 10 seconds to start your request. Every turn in that wake session goes
to the same stateful Gemini chat, so follow-ups retain their context and the
handoff wording varies naturally. Say "ask Groq," "use Groq," "double-check
that," or "get a second opinion" to make Gemini consult the GroqCloud-hosted
GPT-OSS 120B model and synthesize one answer. Groq and xAI's Grok are different
products; a `gsk_` key belongs to GroqCloud and does not provide Grok access.

- Ask another question directly to continue without repeating the wake phrase.
- Say **"wait"** or otherwise ask for more time to keep the conversation open
  through any length of silence.
- Say **"rest for now"**, or naturally tell Jarvis you are finished, to return
  to passive wake-word mode. Gemini interprets answers like "yes" in context,
  so "yes, another fact" continues while "yes, that's all" ends the session.

You should hear a beep and see a "heard: ..." line. Too many false fires, or
missed detections from across the room? Tune
`WAKE_THRESHOLD` in `.env` (higher = fewer false positives, lower = more
sensitive) and rerun. Every detection (real or false) is logged to
`~/Library/Logs/jarvis/jarvis.log`.

Conversation timing can also be tuned in `.env`: `SPEECH_START_TIMEOUT_S`
controls how long Jarvis waits for speech to begin, while `SILENCE_TIMEOUT_S`
controls how much silence marks the end of a spoken request. The default keeps
the full 10-second start window but ends an utterance after about 0.9 seconds of
silence, removing roughly 0.6 seconds from every response without rushing you
before you begin.

Whisper and Kokoro warm in the background as soon as the listener starts, using
their local cached model snapshots without a network revision check. Confirmed
local actions are spoken immediately after execution instead of making a second
Gemini request just to generate "done." A normal local action therefore uses
one model round trip; a visual locate-and-click uses two instead of three.

### When a video is playing

Jarvis temporarily mutes Mac output while it is waiting for your request. It
waits a fraction of a second for the last speaker sound to decay, clears audio
captured before the mute, records you, and restores the exact previous mute
state before transcribing or answering. This prevents dialogue from a video,
podcast, or song from becoming the request.

This is enabled by default. Set `MUTE_OUTPUT_WHILE_LISTENING=false` in `.env` if
you use headphones or prefer to disable it. The mute covers only the listening
window; it does not pause the video or change the stored volume percentage.

### Live clock, timers, and volume

Gemini can now request a small allow-list of validated local actions. Try these
in the full voice loop:

- "Set a tea timer for 10 seconds."
- "How much time is left?" or "Cancel the tea timer."
- "What is the exact date and time?"
- "Lower the volume a little," "set volume to 35 percent," or "mute it."

Timers ring aloud even after the conversation ends and Jarvis returns to
wake-word mode. Multiple named timers are supported. They currently live for
the lifetime of the running Jarvis process, so quitting Jarvis or rebooting the
Mac clears them. Timer creation requires full voice mode; exact time and volume
actions also work through `--text`.

The action vocabulary is fixed in Python: Gemini interprets natural language,
but it cannot turn these requests into arbitrary shell commands. Volume levels
are clamped to 0–100, timer lengths are limited to 1 second–7 days, and Gemini
only confirms an action after macOS reports the result.

### Apps, searches, and Spotify

Jarvis resolves an app name against real installed `.app` bundles before it is
allowed to launch anything. Gemini can request up to three actions per step and
continue bounded multi-step requests after inspecting the evidence. Examples:

- "Open Spotify and play music."
- "Play God's Plan" or "play God's Plan by Drake."
- "Pause Spotify," "next song," or "go back one track."
- "Lower Spotify a little" or "set Spotify volume to 25 percent."
- "What is currently playing on Spotify?"
- "Search Spotify for Daft Punk."
- "Search YouTube for an M2 Mac repair guide."
- "Open Notes," "open Chrome," or "open Calendar."
- "Research today's AI news" for Jarvis's sourced spoken summary, or "search
  the browser for today's AI news" to show results on screen.

Spotify's installed Mac app exposes native play, pause, next, previous,
now-playing, app-specific volume, and direct track-URI playback, so those work
without another API key. Spotify volume commands change only Spotify's internal
0–100 level; ordinary volume commands still control the Mac's master output.
For "play [song]," Jarvis performs a focused public lookup, accepts only a
validated `https://open.spotify.com/track/...` result, converts its 22-character
track ID to a Spotify URI, and starts it. Say the artist or version when a title
is ambiguous. Personal playlists, queue management, and account-library access
still require Spotify OAuth and will be a separate integration.

### Creating Apple Notes

Say, for example, "Create a note called Shopping and type buy milk and coffee
in it." Jarvis creates it in the default Notes account/folder, opens Notes to
the new item, and confirms success only after Notes returns that item's unique
ID. Dictated text is HTML-escaped and passed as a process argument, so quotes,
newlines, and markup cannot become AppleScript code.

Opening Notes alone never counts as creating a note. If a requested app action
does not have a real local tool yet, Jarvis is instructed to say that honestly
instead of pretending it completed the work.

### Time-limited screen vision

Screen assistance starts **off**. Enable it from the Jarvis menu, or say
"Look at my screen" during a voice conversation. The main display gets a
light, click-through cyan tint; the menu shows a live countdown. Access lasts
30 minutes by default, with a hard maximum of 30 minutes. You can explicitly
request a shorter session, for example "Look at my screen for two minutes."
Follow-up questions do not renew the timer.

Say **"screen off"**, "stop looking at my screen," or "privacy mode" while
Jarvis is listening to revoke access locally without a Gemini request. Voice
barge-in during model processing or spoken output is not implemented yet;
use **Stop Screen Assistance** in the menu at those times. Stop Jarvis, Quit
Jarvis Menu Bar, and the timeout also revoke access. Voice/text processes share
the same consent; revocation invalidates pending screenshot-based clicks.
Keep the menu-bar controller running for the visible indicator.

While enabled, a fresh main-display image accompanies each user request to
Gemini, so visual requests no longer need a separate discovery round trip.
Images are resized to at most 1600 pixels on the longest edge and encoded as
JPEG; temporary PNGs are deleted locally. Processed images are removed from
subsequent chat history, while textual findings remain. Provider-side handling
is separate from this local cleanup. This is not continuous recording and does
not capture system audio. Visible captions,
slides, diagrams, application UI, chess puzzles, practice, and games against
the computer are suitable. For a visible game state, Jarvis leads with the
recommended move and a short reason instead of a fair-play lecture. Audio-only
video content is not available through screenshots.

During that same limited session, Jarvis can now scroll the active application
and single-click a target it just inspected. Examples: "scroll down," "go back
up a little," or "play the second video on screen." Visible-target clicks use
screen-relative coordinates so Retina scaling does not shift the target. A
click is allowed only within 15 seconds of a fresh screenshot, each screenshot
permits one click, and scrolling invalidates the prior screenshot. The pointer
briefly rests on the selected target before the click lands so the action is
visible. Browser scrolling uses the page's scroll position and checks for
movement or a boundary; generic Mac wheel events cannot prove movement and
are reported only as sent. Supported YouTube requests can press an available
Skip Ad button, not skip an unskippable ad. Jarvis does not use visual clicks
for typing, purchases, sending,
deleting, account changes, or permission dialogs.

macOS setup: enable **System Settings → Privacy & Security → Screen & System
Audio Recording** for the process that launches Jarvis (Terminal, VS Code,
PyCharm, etc.). Also enable it under **Privacy & Security → Accessibility** for
scrolling and clicking; the first attempted input action asks macOS to show this
permission prompt. Enable the listed launcher, then fully restart it. Screenshots
leave the Mac when sent to the configured Gemini API, so keep sensitive windows
closed during an active vision session.

### Web research

Ask naturally: "search the web for...", "research...", "what is the latest...",
or "verify...". Gemini decides on focused queries, Jarvis searches the public
web without another API key, and Gemini selects up to two result pages to read
before synthesizing an answer. Searches, page reads, and clickable source URLs
appear in Terminal as `[web]` lines while the spoken answer stays concise.

Google's native Search grounding is not available on this project's free Gemini
API tier, so Jarvis uses the keyless `ddgs` search client instead. Page reads are
bounded, restricted to public HTTP(S) addresses, and treat page text as untrusted
evidence. JavaScript-only sites, paywalls, and non-HTML files may not be readable.

## Project layout

```
jarvis/
├── jarvis/
│   ├── main.py           # entry point, the loop
│   ├── config.py         # env vars, constants
│   ├── audio.py          # mic stream, recorder
│   ├── wake.py           # openWakeWord wrapper -- wake phrase is "hey jarvis"
│   ├── stt.py            # Whisper wrapper
│   ├── speak.py          # local neural TTS (Kokoro-82M)
│   ├── llm.py            # stateful Gemini chat + conversation actions
│   ├── groq.py           # GPT-OSS 120B specialist + safe answer fallback
│   ├── menu_bar.py       # login-launched start/stop status controller
│   ├── status.py         # atomic voice-process → menu activity channel
│   ├── web.py            # keyless search + safe public-page reader
│   ├── actions.py        # validated clock/timer/macOS volume actions
│   ├── apps.py           # installed-app launch/search + Spotify playback
│   ├── notes.py          # verified Apple Notes creation
│   ├── screen.py         # expiring authorization + ephemeral screenshots
│   ├── timers.py         # monotonic multi-timer scheduler
│   ├── router.py         # legacy handler registry; future tool plumbing
│   └── handlers/         # deterministic local integrations/tools
├── tests/
│   ├── audio_check.py         # Phase 0 checkpoint script
│   ├── test_audio.py          # recorder timing tests
│   ├── test_conversation.py   # multi-turn session tests
│   ├── test_llm.py            # Gemini research orchestration tests
│   ├── test_groq.py           # second-provider schema/history tests
│   ├── test_menu_bar.py       # process/login-item tests without a GUI
│   ├── test_status.py         # cross-process activity-state tests
│   ├── test_stt.py            # speech-model warm-up tests
│   ├── test_web.py            # search/page safety and extraction tests
│   ├── test_actions.py        # local action validation tests
│   ├── test_apps.py           # safe app/search/Spotify command tests
│   ├── test_notes.py          # safe note creation and escaping tests
│   ├── test_screen.py         # authorization/expiry/deletion tests
│   ├── test_timers.py         # deterministic scheduler tests
│   └── test_handlers.py       # router/handler tests
├── .env.example
├── requirements.txt
└── PLAN.md
```

Gemini handles language and follow-up context. Computer-control features are
exposed as explicit local tools so Gemini can request an action and Jarvis can
execute it safely instead of pretending it happened.

## Contributing (just the two of us)

- `main` stays runnable. Branch per phase/feature (`phase-3-media`), review
  before merge, even a two-line one.
- Secrets go in `.env` (gitignored) — never in code, never in a commit.
- `pip freeze > requirements.txt` after adding a dependency, so both machines
  stay in sync.

See PLAN.md section 7 for the full working agreements.
