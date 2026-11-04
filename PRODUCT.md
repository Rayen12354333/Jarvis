# Jarvis — product analysis and current build

The goal is a Mac that is easier to operate and easier to work with: say or
type what you need, see what happens, and recover cleanly when something
cannot be done. This is the product plan, not a business plan. Hand gestures
come after voice, text, and computer actions are dependable.

Jarvis is currently an Apple-Silicon/macOS menu-bar assistant built around
existing models. It is not a newly trained foundation model, a Windows app,
or a browser extension that automatically controls every application.

## The product decision

The central experience should be **a useful task completed with evidence**.
A pleasant answer does not prove that Notes was created, music started, or
research was saved. Speed, correct targeting, visible progress, persistent
useful work, and honest failure handling are the immediate priorities.

The first distinctive capability being developed is **Work Sessions**:
research or understand something, save the useful findings with sources,
record a decision and a next step, then resume that work later. Voice control,
browser context, public-source reading, local storage, and a Markdown handoff
become one workflow. This is a differentiation hypothesis for Jarvis—not a
claim that no other product offers memory or workspaces.

Example payoff: a student reads a difficult page, asks for an explanation,
saves the key ideas with their source, and returns tomorrow to the next
revision step without reconstructing the conversation. The same mechanics
can support research projects and planning. Specialized professional skills
need their own quality checks before being advertised as supported.

## What the code audit found and changed

1. **Premature completion.** The previous latency shortcut ended a request after
   an apparently successful local action, potentially dropping later steps.
   Completion is now explicit; only recognized execution confirmations may
   bypass another model call. Multi-step work continues after tool evidence.
2. **Unsupported success claims.** Pre-action model wording could be spoken as
   if it proved completion. The fast path now speaks controller evidence.
   System/Spotify volume changes and Spotify playback use state readback.
   Opening a selected YouTube video is distinct from verified playback.
3. **Context gaps.** Fast-path action results were missing from the next model
   turn. They are now retained. Ordinary chat remains session-lifetime;
   explicitly saved work survives restarts in local SQLite.
4. **Ambiguous resume.** A live test interpreted “resume Launch research” as a
   new session named “Launch.” Resume now has a separate existing-only action.
   An unknown name cannot silently create an empty session.
5. **Fragile targeting.** Screen clicks now check foreground PID and capture
   authorization revisions in addition to freshness. Supported browser actions
   use observed links and tab/window guards rather than guessed coordinates.
6. **Invisible delays.** Listening, recognition, model calls, local actions,
   synthesis, and playback all contribute latency. Status labels, action
   receipts, stage timing, background model warm-up, and typed requests make
   these stages observable. Independent public research reads run concurrently.
7. **Stale research.** Process-lifetime caches could return old facts forever.
   Search/page caches now expire after at most 60/300 seconds respectively.
   This is bounded freshness, not continuous real-time event monitoring.
8. **Permission ambiguity.** Setup diagnostics show the actual executable and
   read-only permission state. Stable signed-app onboarding is still needed.
9. **Shutdown cleanup.** Default SIGTERM could skip listening-mute restoration.
   Menu Stop now unwinds voice cleanup. Forced termination/crashes still cannot
   guarantee cleanup or undo actions that have already completed.

## Try this build

After reloading the updated menu-bar process:

- **Start Jarvis / Stop Jarvis:** control the wake-word listener.
- **Type a Request:** ask without a microphone or spoken reply. Stop voice first;
  this version prevents the two modes from controlling the Mac concurrently.
  Stopping voice clears its in-memory timers.
- **Read New Reply / Last Typed Reply:** read the answer and elapsed time.
  Completion marks the menu “Reply ready”; it does not steal focus from the
  application Jarvis just controlled.
- **Cancel Typed Request:** prevent subsequent steps. In-flight network calls
  must return, and an operation already sent to macOS may already have happened.
- **Recent Actions:** see actual tool results and execution times. “Result”
  means a tool returned evidence, not that the entire task succeeded.
- **Setup & Permissions:** inspect configuration without displaying keys or
  automatically granting access.
- **Open Exported Work Sessions:** reveal saved Markdown handoffs.
- **What Can Jarvis Do?:** open this guide.

Typed follow-ups share a conversation until you end/cancel it or quit the menu.
Voice wake sessions keep separate conversational context. Work Sessions are
the explicit bridge across modes and restarts.

### A work session you can continue tomorrow

Try these in order, by voice or through Type a Request:

1. “Start a work session called Biology revision.”
2. “Save this next step: review cell division tomorrow.”
3. “What is the saved next step in Biology revision?”
4. “Export my work session.”
5. After ending/restarting the conversation: “Resume Biology revision and tell
   me where I left off.”

Resume selects an existing exact name and cannot create a new session. If the
stored name is unknown, Jarvis should list saved sessions before selecting one.

For research: “Research spaced repetition and save three useful findings with
their source links in Biology revision.” Then ask for a decision or next step
and explicitly ask to save it. Exported Markdown includes the entire saved
history. A model read sees bounded recent entries; older entries are retained,
not deleted. The store does not automatically remember every conversation.

### Browser assistance

Native support is limited to Safari and Google Chrome:

- “Open YouTube in Safari.”
- With the intended browser in front: “Explain this page.”
- “Read this page and save a short summary with its source in my work session.”
- On a visible YouTube results/home/recommendations page: “Play the second video.”
- “Go back in Safari,” “go forward,” or “reload this page.”

The page reader reads the current visible viewport, not every tab or a complete
article. It excludes form/editable values and caps text at 8,000 characters.
There is no silent browsing monitor. Page text and video selection need the
browser's JavaScript-from-Apple-Events permission plus macOS Automation where
required. Title/URL may still be available when page text is not. Jarvis does
not enable these permissions itself.

“Second video” means the second visible standard organic video in reading
order. Ads and Shorts are excluded. The controller validates the observed
YouTube link and rejects switched tabs/windows. Loading, autoplay policy, and
future YouTube layout changes can still prevent playback. A pre-roll ad does
not count as the requested content being verified as playing.

Generic screen assistance remains opt-in. Enable it from the menu or by voice;
a light cyan main-display tint and countdown show when it is active. Default
and maximum duration are 30 minutes, without automatic renewal on follow-ups.
Each user request during the session can include a fresh screenshot. Menu
Stop Screen Assistance, voice "screen off" while listening, Stop Jarvis, Quit,
and expiration revoke it. Voice barge-in while processing/speaking is not yet
available; the menu stop remains available. Screenshots cover the main display.
An app PID guard cannot detect every
same-app window/tab/layout change; prefer native browser controls where supported.

Browser scroll now reads back position and distinguishes actual movement from
an already-reached edge. Generic Mac scroll events report only that an event
was sent. YouTube has a dedicated visible Skip Ad button action, separate from
Spotify. Browser JavaScript permissions are still required for these controls.

## Current capability boundary

Available code paths include wake-word/typed conversation, public-source
research, exact local time, voice-process timers, system volume, Spotify
controls, installed-app launching, supported app searches, verified Apple
Notes creation, temporary screenshot assistance, bounded click/scroll,
supported browser operations, and persistent Work Sessions.

This is not universal computer control. Not implemented yet: arbitrary editing
and typing across apps, Finder organization with undo, calendar/email OAuth
workflows, Spotify library/playlist management, continuous video/audio
understanding, universal UI automation, or hand tracking. Opening an app does
not implement work inside that app.

Generic model-selected clicks have prompt restrictions and local permission/
freshness guards, but the program cannot yet independently classify every
target as harmless. Do not use the prototype for unattended consequential
actions. Purchases, sending, deletion, account/security changes, and permission
dialogs are outside the intended click workflow. There is no model-provided
arbitrary shell, AppleScript, or JavaScript execution tool.

## Data and control

- Wake detection, Whisper transcription, and Kokoro synthesis run locally.
  Gemini receives requests and any specifically requested page, research,
  saved-session, or screenshot context needed to answer. Optional GroqCloud
  provides second opinions and answer-only fallback.
- While explicitly enabled, screen mode adds one fresh image to each user
  request. Uploads have a 1600-pixel longest-edge limit; previously processed
  images are removed from later model requests to avoid growing latency.
  Textual findings remain. This does not delete data at the model provider.
- Work sessions are stored at
  `~/Library/Application Support/Jarvis/workspaces.sqlite3`. Markdown exports
  live in the neighboring `Workspaces` folder. Files have private permissions;
  exports get unique names and do not overwrite earlier exports.
- Storage is **not application-level encrypted**. Saved content can be sent to
  the configured model when you ask Jarvis to read/use it. Screenshot files
  are temporary, but submitted images are processed by the model provider.
- Recent action history is limited to 20 receipts at
  `~/Library/Logs/jarvis/recent-actions.json`. Browser/work-session read content
  is omitted. Existing general voice logs may contain utterances and source
  links; they are not a fully privacy-redacted transcript.
- Saving work is explicit. No automatic personal-memory collection, continuous
  desktop recording, or background camera use. `.env` remains ignored by Git;
  rotate credentials previously exposed in chat before sharing the product.
- Webpage, screenshot, and saved-note content is untrusted evidence, never a
  new user instruction. Prompts alone are not a complete security boundary;
  adversarial evaluation remains a public-release requirement.

## Development order and release gates

### 1. Make everyday tasks consistently correct

Maintain a regression set of at least 30 ordinary requests: system/Spotify
volume, the requested browser, selected-video playback, reading the intended
page, exact notes, the correct saved session, cancellation, denied permissions,
and an unavailable model.

Release gate: no silent wrong-target changes, duplicate creations after an
uncertain result, or success claims for observed failures. Measure warm/cold
latency separately, including last spoken word to first audible answer—not
just model time. Aim for warm simple actions around two seconds after
transcription, with separate median and slow-tail measurements. This is a
target, not a claim that all current voice requests meet it.

Next speech work: evaluate incremental synthesis, better end-of-utterance
detection, push-to-talk, interruption during speech, and transcript correction.
Measure recognition accuracy alongside speed; a quick wrong action is not an
improvement. The current listener still mutes speaker audio while recording.

### 2. Build one complete task skill at a time

- Study/research: source-backed explanations, structured summaries, revisiting
  saved sources, and useful decisions/next steps.
- Files: user-selected folders, previews, exact paths, recoverable operations,
  and an undo journal before broad organization commands.
- Calendar/email: scoped OAuth and account selection, read-only first, then
  drafts and explicit approval before sending or changing events.
- App editing: semantic Accessibility controls, target verification, task
  tests, and confirmation before consequential submissions.
- Reusable routines: named user-reviewed steps, visible progress, per-step
  evidence, cancellation, and recovery—not arbitrary unattended scripts.

Every skill needs success evidence and failure behavior. Stronger models can
help interpretation, but cannot replace missing app APIs, permissions,
verification, or undo. Routine actions should keep the short path; second
opinions should be deliberate because they add network latency.

### 3. Make installation and daily operation dependable

Still needed: a signed/notarized app with stable identity, permission onboarding,
Keychain credentials, dependency locking, bounded logs, opt-in redacted crash
reporting, updates/rollback, persistent timers with overdue behavior, and one
shared action queue for voice/text. The screen-access countdown, cyan tint,
30-minute limit, and direct revoke control are implemented; packaging and the
other operational requirements listed here remain unfinished.
No billing, marketing, or business work is needed to build them.

### 4. Add optional hand movement input after polishing

Gestures should feed the same validated actions as voice/text. Start with an
explicit camera-on session and visible indicator, process landmarks on-device,
and keep camera frames out of cloud models by default.

Prototype a few deliberate gestures: palm to pause listening, pinch to confirm
a highlighted target, and controlled scrolling. Require hold/confidence
thresholds, cooldown, and an easy disable control. Casual movement must not
trigger clicks, sending, purchases, or deletion.

Test accidental activations, low light, left/right hands, fatigue, battery/CPU
cost, and accessibility alternatives. The product must remain fully usable
without a camera. Hand tracking is not enabled in this build.

## Verification

Offline tests use fake model/Mac adapters plus real temporary SQLite files.
They cover continuation, failure, duplicates, cancellation, persistence/export,
URL validation, permission failures, screen focus/authorization, menu focus
restoration, and bounded history. They do not prove every app and permission
works on every Mac.

From the project directory:

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check jarvis tests
.venv/bin/python -m jarvis.diagnostics
PYTHONPATH=. .venv/bin/python tests/live_smoke.py --live
PYTHONPATH=. .venv/bin/python tests/performance_smoke.py --live --tts
```

The opt-in smoke test consumes a few Gemini requests with synthetic data,
simulated computer/browser actions, and real temporary work-session storage.
It does not control Spotify, capture the screen, or create a real user session.
Measured results and outstanding manual checks are recorded in `PROGRESS.md`.
The performance smoke test uses a generated number image, repeated Gemini
requests, and local speech synthesis without playback. It does not measure a
real microphone-to-action workflow or inspect the user's screen.
