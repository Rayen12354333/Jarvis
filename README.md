# Jarvis

A voice-activated assistant for macOS: wake word, system/media control, email
summaries, and a daily academic briefing. Local-first — wake word, speech-to-
text, and text-to-speech all run on-device.

The full design doc, phase-by-phase plan, and the reasoning behind every
decision (why Porcupine, why no LLM in the hot path, why we didn't just fork
an existing Jarvis repo) lives in **[PLAN.md](./PLAN.md)**. Read that first.

**Status:** Phase 0 — environment setup.

## Quickstart

```bash
# 1. System dependencies (macOS, Homebrew)
xcode-select --install        # if not already installed
brew install python@3.11 portaudio ffmpeg

# 2. Virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Secrets
cp .env.example .env
# then edit .env and add PICOVOICE_ACCESS_KEY (free: https://console.picovoice.ai)

# 4. Phase 0 checkpoint
python tests/audio_check.py
```

macOS will ask for Microphone / Accessibility / Automation permissions the
first time you run something that needs the mic or system control. Grant
these to **whatever process actually runs the script** — if you run it from
VS Code's integrated terminal, VS Code needs the permission, not Terminal.app
(macOS grants permissions to the parent process). See PLAN.md, Phase 0.

## Running it

```bash
# Full voice loop
python -m jarvis.main

# Skip the mic, test a handler directly (Track B, PLAN.md section 6)
python -m jarvis.main --text "what time is it"
```

## Project layout

```
jarvis/
├── jarvis/
│   ├── main.py           # entry point, the loop
│   ├── config.py         # env vars, constants
│   ├── audio.py          # mic stream, recorder
│   ├── wake.py           # Porcupine wrapper
│   ├── stt.py            # Whisper wrapper
│   ├── speak.py          # TTS (macOS `say`)
│   ├── router.py         # handler registry + dispatch
│   └── handlers/         # one file per feature -- see PLAN.md section 3
├── tests/
│   ├── audio_check.py    # Phase 0 checkpoint script
│   └── test_handlers.py  # pytest for handlers
├── .env.example
├── requirements.txt
└── PLAN.md
```

Adding a feature = adding one file to `jarvis/handlers/`. It's auto-imported
and auto-registered; nothing else needs to change.

## Contributing (just the two of us)

- `main` stays runnable. Branch per phase/feature (`phase-3-media`), review
  before merge, even a two-line one.
- Secrets go in `.env` (gitignored) — never in code, never in a commit.
- `pip freeze > requirements.txt` after adding a dependency, so both machines
  stay in sync.

See PLAN.md section 7 for the full working agreements.
