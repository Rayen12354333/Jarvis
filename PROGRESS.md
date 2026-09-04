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

- **Phase 0 (env setup):** done.
- **Phase 1 (wake word):** done. "hey jarvis" via openWakeWord, tuned and
  debounced.
- **Phase 2 (listen → transcribe → route → speak):** done. Full loop works:
  say "hey jarvis", say a command, faster-whisper transcribes it, router
  dispatches to a handler, Kokoro speaks the reply back.
- **LLM fallback layer (Gemini):** added. `router.dispatch()` now calls
  Gemini when no regex handler matches, instead of just giving up. Pending:
  user needs to paste a real `GEMINI_API_KEY` into `.env` and test it live —
  not yet confirmed working end-to-end (code is written, untested with a
  real key as of this entry).
- **Phase 3 (media control — volume/play/pause/next/previous):** not started.
  This is the next step.
- **Phases 4-7 (menu bar app, Gmail, SUIS briefing, extras):** not started.

### Key config (`.env`, gitignored — not in the repo, this is what's set locally)
```
WAKE_WORD_MODEL=hey_jarvis
WAKE_THRESHOLD=0.75          # bumped from 0.5, see session log
WHISPER_MODEL=base.en
WHISPER_COMPUTE_TYPE=int8
VOICE_NAME=am_adam           # Kokoro voice id (American male)
VOICE_SPEED=1.0              # normal speed for now, will revisit later
GEMINI_API_KEY=              # get free at aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.5-flash-lite
```

### Stack decisions that differ from the original PLAN.md write-up
- **Wake word:** openWakeWord, not Porcupine. Picovoice (Porcupine) killed its
  free/non-commercial tier — see PLAN.md section 2 for the full writeup.
- **TTS:** Kokoro-82M via `kokoro-mlx`, not macOS `say`. Free, local,
  Apple-Silicon-native, far more natural than the built-in `say` voices.
  Voice picked: `am_adam`. Other voices tested: `bm_daniel`, `bm_fable`,
  `bm_george`, `bm_lewis` (British male options, none picked yet — revisit
  later if `am_adam` gets old). Kokoro also supports a `speed` multiplier;
  user wants a faster/"spicier" delivery eventually but that's deferred —
  Kokoro has no tone/emotion knob, so "spicy" will have to come from how
  handler reply text is written (short, punchy lines) rather than a model
  setting.

### Known issues / open items
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
  (blank until user pastes a real one) and `GEMINI_MODEL` (default
  `gemini-2.5-flash-lite`).
- `requirements.txt` -- added `google-genai`.

**Not yet done:** user hasn't pasted a real API key in yet, so this is
untested end-to-end. Next real step here is getting a key from
aistudio.google.com/apikey, running `pip install -r requirements.txt`, and
testing with something like `python -m jarvis.main --text "tell me a fun fact"`
(a phrase no regex handler matches, to force the fallback path).

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

Phase 3 — media control (PLAN.md's "the real milestone"):
- Volume up/down/mute/set via `osascript set volume`.
- Play/pause/next/previous via system-defined media key events (pyobjc), so
  it drives whatever app is actually playing rather than one hardcoded app.
- New handler file: `jarvis/handlers/media.py` already exists as a stub —
  check its current contents before starting, it may already have partial
  work.
