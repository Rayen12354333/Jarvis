# Jarvis — Build Plan

A voice-activated assistant for macOS. Wake word, system/media control, email
summaries, and a daily academic briefing.

**Team:** 2 developers
**Target machine:** MacBook Air/Pro, Apple M2, 8 GB unified memory
**Language:** Python 3.11
**Status:** Phase 0 (environment setup)

---

## 1. Scope

### In scope
1. **Voice-controlled system/media control** — wake word "Jarvis", volume up/down,
   play/pause, mute. Must work from across the room. Controls whatever is
   actually playing, not a specific app.
2. **Email summarization** — spoken summary of unread Gmail: sender, topic,
   anything urgent. Read-only, no drafting or sending.
3. **Academic daily briefing** — "what do I have to do today?" answered from
   Google Calendar and/or Sabanci SUIS.
4. **Everyday extras** — timers, weather, quick lookups. Later, not now.

### Out of scope
Vision/webcam, HUD or custom UI, multi-user support, non-macOS platforms,
persona customization.

### Non-functional requirements
| Requirement | How we meet it |
|---|---|
| Hands-free wake word | Porcupine always-on listener, no hotkey |
| Ignores background noise | Wake word gate + Whisper confidence threshold |
| Fast simple commands | Regex fast-path, no LLM in the hot loop |
| Local-first / private | Wake word, STT, and TTS all run on-device |
| Extensible | Decorator-based handler registry, one file per feature |
| Runs persistently | Menu bar app (rumps) + launchd login item |

---

## 2. Key decisions (and why)

**We are not forking an existing Jarvis repo.**
We surveyed the field. The highest-starred "Jarvis" repos are portfolio
projects with hardcoded if/elif command chains and no plugin architecture.
The serious options each failed on something specific:

| Candidate | Stars | Why not |
|---|---|---|
| `isair/jarvis` | ~1.7k | Best off-the-shelf option, but routes every utterance through a local LLM needing 8 GB+ VRAM. Not viable on an 8 GB M2, and adds latency to "volume up". License is personal-use-free, not OSI. |
| `leon-ai/leon` | ~17.5k | Mid-rewrite to a 2.0 developer preview; current docs describe the legacy architecture. Server-oriented, not a Mac desktop agent. |
| OpenVoiceOS | — | Genuine Mycroft successor with real skill plugins and macOS installer support, but it's a multi-daemon smart-speaker stack. Too heavy for four features. |
| `thevickypedia/Jarvis` | ~254 | Excellent macOS engineering, MIT, 1 open issue. Effectively one maintainer, pinned to Python 3.10/3.11, huge feature surface to strip. **We read this for reference.** |
| `MycroftAI/mycroft-core`, `rhasspy/rhasspy` | 6.6k / 2.7k | Both formally archived. Ignore tutorials pointing here. |

**Correction, Sept 2026 -- Porcupine is dead for us, switched to openWakeWord.**
Picovoice discontinued its free/non-commercial tier entirely as of June 30,
2026 ("focusing on our core business, enterprise deployments... no
non-commercial tier planned"). Console signup now requires a company email
and rejects personal addresses outright. That kills the "needs a free
AccessKey" tradeoff this table originally accepted -- there is no free key
anymore, at any tier, full stop.

We switched to openWakeWord (already our listed fallback). Two things that
looked like blockers turned out not to be:
- It ships a pretrained **"hey jarvis"** model out of the box -- no training
  needed, no custom phrase work.
- The Apple Silicon ONNX bug below is still open upstream
  (dscripka/openWakeWord#336), but current openWakeWord versions default to
  the **tflite** backend and import `ai_edge_litert.interpreter` directly --
  no TensorFlow, no hand-written shim. `pip install ai-edge-litert` (which
  ships real macOS ARM64 wheels, unlike `tflite-runtime`) is the whole fix.

`jarvis/wake.py`, `config.py`, `.env.example`, and `tests/audio_check.py` are
already updated. `WAKE_WORD` -> `WAKE_WORD_MODEL` (default `hey_jarvis`),
`WAKE_SENSITIVITY` -> `WAKE_THRESHOLD`. No AccessKey, no signup, nothing in
`.env` for wake word at all.

**No LLM in the hot path.**
8 GB unified memory means a resident language model competes with the browser.
Volume and media commands are deterministic — they get regex matching and a
keypress. We revisit a small model only for the email summary, in Phase 5.

**[Superseded -- see correction above] Porcupine over openWakeWord.**
openWakeWord ships a pretrained "hey jarvis" model and needs no account, but
has an open bug where the ONNX backend returns near-zero scores on Apple
Silicon, so detection silently never fires. The workaround requires installing
TensorFlow plus a hand-written `tflite_runtime` shim — half a gigabyte we can't
spare. Porcupine is native arm64, ~20 KB of model RAM, and ships free
predefined wake phrases. It needs a free AccessKey, but detection still runs
entirely on-device. openWakeWord stays as our fallback.

**Idle memory budget:** wake word ~10 MB, Whisper base.en ~200 MB (loaded on
demand), TTS 0 MB (macOS `say`), app ~100 MB. Under 400 MB total.

---

## 3. Architecture

```
mic stream (16 kHz)
      │
      ▼
[ wake word ]  Porcupine — always on, ~10 MB
      │  detected "Jarvis"
      ▼
[ recorder ]   capture until ~1s silence, max 8s
      │
      ▼
[ STT ]        faster-whisper base.en, loaded on demand
      │  text
      ▼
[ router ]     match text against registered handler patterns
      │
      ├──► handlers/media.py     volume, play/pause, mute
      ├──► handlers/email.py     Gmail summary
      ├──► handlers/briefing.py  Calendar + SUIS
      └──► handlers/misc.py      timers, weather
      │
      ▼
[ speak ]      macOS `say`
```

### Directory layout

```
jarvis/
├── jarvis/
│   ├── __init__.py
│   ├── main.py           # entry point, the loop
│   ├── config.py         # env vars, constants
│   ├── audio.py          # mic stream, recorder, VAD
│   ├── wake.py           # Porcupine wrapper
│   ├── stt.py            # Whisper wrapper
│   ├── speak.py          # TTS
│   ├── router.py         # registry + dispatch
│   └── handlers/
│       ├── __init__.py   # auto-imports every handler module
│       ├── media.py
│       ├── email.py
│       ├── briefing.py
│       └── misc.py
├── tests/
├── .vscode/settings.json
├── .env                  # secrets — NEVER committed
├── .env.example           # committed, keys blank
├── requirements.txt
└── README.md
```

### The handler contract

Every feature is one file. Adding a command never touches the core loop.

```python
from jarvis.router import handler

@handler(r"\b(volume|sound)\s+(up|down)\b", name="volume")
def adjust_volume(match, text):
    direction = match.group(2)
    ...
    return "Volume up."   # spoken back; return None to stay silent
```

Rules:
- Patterns are case-insensitive regex, matched in registration order.
- A handler returns a short string to speak, or `None`.
- A handler must never block for more than ~2 seconds without saying something
  first ("Checking your email...").
- Anything slow (network, Selenium) runs in a thread; the listener stays live.

---

## 4. Stack and links

### Libraries we depend on
| What | Package | Link |
|---|---|---|
| Wake word | `pvporcupine` | https://github.com/Picovoice/porcupine |
| Speech-to-text | `faster-whisper` | https://github.com/SYSTRAN/faster-whisper |
| Mic capture | `sounddevice` | https://github.com/spatialaudio/python-sounddevice |
| Menu bar app | `rumps` | https://github.com/jaredks/rumps |
| Media keys | `pyobjc` | https://github.com/ronaldoussoren/pyobjc |
| Gmail (Phase 5) | `google-api-python-client` | https://github.com/googleapis/google-api-python-client |
| SUIS scraping (Phase 6) | `selenium` | https://github.com/SeleniumHQ/selenium |
| Fallback wake word | `openwakeword` | https://github.com/dscripka/openWakeWord |

AccessKey signup (free): https://console.picovoice.ai

### Reference repos — read, don't clone
| Repo | Read it for |
|---|---|
| https://github.com/thevickypedia/Jarvis | macOS permissions, volume/brightness key handling, background task scheduling |
| https://github.com/isair/jarvis | Echo detection, follow-up handling, Whisper hallucination filtering |
| https://github.com/OpenVoiceOS/ovos-installer | launchd persistence patterns on macOS |
| https://github.com/KoljaB/RealtimeSTT | Voice activity detection and streaming transcription |

---

## 5. Phases

Each phase ends at a checkpoint that either works or doesn't. Don't start the
next phase until the checkpoint passes on **both** machines.

### Phase 0 — Environment (both, together)
- Xcode CLT, Homebrew, Python 3.11, `portaudio`, `ffmpeg`
- venv, VS Code + Python/Pylance/Ruff, interpreter pointed at `.venv`
- macOS permissions: add **both VS Code and Terminal** to Microphone,
  Accessibility, and Automation. macOS grants permissions to the parent
  process, so a script run from VS Code's terminal inherits VS Code's
  permissions, not Terminal's.
- Picovoice AccessKey in `.env`

**Checkpoint:** `tests/audio_check.py` lists the mic, prints Porcupine's
keyword list, and reports a non-silent peak amplitude.

### Phase 1 — Wake word listener
- `wake.py`: continuous 16 kHz stream into Porcupine
- Console beep + log line on detection
- Sensitivity tuning; test from 3–4 m across the room
- False-positive log over a normal working day

**Checkpoint:** Detects "Jarvis" reliably from across the room; fewer than ~2
false fires per hour of background conversation.

### Phase 2 — Listen, transcribe, route
- `audio.py`: record after wake until ~1s of silence, cap at 8s
- `stt.py`: faster-whisper `base.en`, `int8` compute type, model loaded once
- `router.py`: the registry, decorator, and dispatch
- `speak.py`: `say` wrapper, non-blocking
- A `handlers/misc.py` with "what time is it" to prove the wiring

**Checkpoint:** "Jarvis, what time is it" → spoken answer in under ~3 seconds.

### Phase 3 — Media control (feature #1, the real milestone)
- Volume up/down/mute/set via `osascript set volume`
- Play/pause/next/previous via system-defined media key events (pyobjc), so it
  drives whatever is playing rather than one hardcoded app
- Phrase variants: "turn it up", "louder", "pause", "stop the music"

**Checkpoint:** Adjust volume and pause a YouTube video from across the room
without touching the keyboard.

### Phase 4 — Always running
- `rumps` menu bar app: status icon, pause listening, quit
- launchd plist for start-on-login
- Log rotation to `~/Library/Logs/jarvis/`

**Checkpoint:** Reboot the Mac; Jarvis is listening without anyone starting it.

### Phase 5 — Email summaries (feature #2)
- Google Cloud project, OAuth desktop credentials, Gmail read-only scope
- Fetch unread from the last 24h; sender, subject, first lines
- **Start with extractive summarization** — no model. Sender + subject +
  urgency keyword flags. Instant, free, and fully private.
- Only if that isn't good enough: a small on-demand Ollama model, loaded for
  the request and unloaded after. Decide with real inbox data, not in advance.

**Checkpoint:** "Jarvis, summarize my emails" → useful spoken rundown in under
10 seconds.

### Phase 6 — Daily briefing (feature #3)
- Google Calendar read-only, today's events
- SUIS scraper: reuse the Selenium approach from the existing registration bot.
  Investigate first whether a plain `requests.Session` with the login POST is
  enough — much lighter and faster than driving a browser.
- Credentials in Keychain, never in the repo
- Cache results; scrape at most every few hours, not per query

**Checkpoint:** "Jarvis, what do I have to do today?" → merged rundown of
classes, deadlines, and calendar events.

### Phase 7 — Extras (feature #4)
Timers, weather, unit conversion, quick web lookup. Each is one handler file.

---

## 6. Work split

The phases are sequential, but the work inside them isn't. Suggested tracks
once Phase 2 lands:

**Track A — Voice core**
`audio.py`, `wake.py`, `stt.py`, `speak.py`, `router.py`, latency tuning,
false-positive reduction, the menu bar app.

**Track B — Integrations**
`handlers/*`, Google OAuth setup, the SUIS scraper, credential storage,
caching.

Track B can develop and test handlers by calling the router directly with text,
no microphone needed:

```bash
python -m jarvis.main --text "summarize my emails"
```

Build that text-input flag in Phase 2. It makes the two tracks independent and
makes everything testable without speaking at your laptop.

---

## 7. Working agreements

**Git**
- `main` stays runnable. Never push a broken `main`.
- Branch per phase or feature: `phase-3-media`, `handler-gmail`.
- PRs reviewed by the other person before merge. Even a two-line review.
- Commit messages: `phase3: add media key events via pyobjc`.

**Secrets**
- Everything sensitive lives in `.env`, which is gitignored.
- `.env.example` is committed with every key present and every value blank.
- Google OAuth token files and SUIS credentials never enter the repo. If one is
  committed by accident, rotate it — don't just delete the commit.

**Code**
- Ruff for formatting and linting, format on save.
- Type hints on anything crossing a module boundary.
- Handlers get a test in `tests/` that calls them with sample text.

**Environment parity**
Both machines run Python 3.11 and install from the same `requirements.txt`
with pinned versions. `pip freeze > requirements.txt` after any new dependency.

---

## 8. Known risks

| Risk | Mitigation |
|---|---|
| Wake word fires on TV/podcast speech | Tune sensitivity; log false positives in Phase 1 before building on top |
| Jarvis hears its own TTS output | Mute the listener while `say` is speaking; echo detection if that's not enough |
| Whisper hallucinates on silence | Drop segments below a confidence threshold and above a no-speech probability |
| 8 GB RAM pressure | No resident LLM; Whisper unloaded after idle timeout |
| macOS permission prompts break the launchd flow | Grant permissions to the packaged app explicitly in Phase 4 |
| SUIS changes its markup | Isolate all scraping in one module; fail loudly rather than reporting stale data |

---

## 9. Open questions

- Whisper `base.en` vs `small.en` — is the accuracy gain worth ~2x latency on M2?
- Does SUIS work with plain session cookies, or does it need full Selenium?
- Should the briefing be push (spoken every morning at 9) or pull only?
- Second wake phrase for a "quiet mode" that shows a notification instead of
  speaking?
