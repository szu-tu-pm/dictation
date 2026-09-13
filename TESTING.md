# Testing dictation

Two layers:

1. **Automated** — logic that should not need a microphone (text cleanup, ring buffer, config, zip safety). Run these after every code change.
2. **Manual** — hold-to-talk, paste, Vulkan, and modifier swallowing. The product is a global hook; pytest cannot speak into Notepad for you.

## 0. One-time setup

In PowerShell:

```powershell
cd C:\Users\gregs\Dictation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
```

Allow the microphone:

1. Windows **Settings → Privacy & security → Microphone**
2. Turn **Microphone access** on
3. Allow **Desktop apps** (and Python / Windows Terminal / Cursor if listed)

Plug in or enable the mic you will talk into. Discord/Zoom can stay open; capture is WASAPI **shared**.

## 1. Automated suite

```powershell
cd C:\Users\gregs\Dictation
.\.venv\Scripts\Activate.ps1
pytest
```

This is fast and does **not** download the 1.6 GB model. It covers filler stripping, ghost transcripts, the audio ring buffer, config round-trip, zip-slip rejection, quiet-audio gating, tray icons, plus cheap Windows checks (WASAPI device present, Right Ctrl hook install/remove, clipboard restore, `whisper.dll` param overlay if the engine is already on disk).

Smoke the same hook/WASAPI path the app uses at startup:

```powershell
python -m dictation --check
```

## 2. First launch (model download)

```powershell
python -m dictation
```

Expect:

| Time | Tray tooltip |
| --- | --- |
| Immediately | Starting / Checking engine |
| If engine missing | Downloading engine … % |
| First run | Downloading model … % (~1.6 GB to `%APPDATA%\Dictation\models\`) |
| After load | **Idle (vulkan)** on this 7900 XTX |

If the tooltip says **Idle (cpu)** or **Error**, open `%APPDATA%\Dictation\dictation.log` and stop. Do not continue the manual list until it says vulkan (or you have knowingly fallen back to CPU).

Quit from the tray when you need to stop. The mic stays open the whole time the icon is visible.

## 3. Manual checklist

Keep the app running. Copy this list and tick as you go.

### A. Happy path (Notepad)

1. Open **Notepad**. Click in the body so the caret is there.
2. Copy some unrelated text (e.g. `CLIPBOARD-BEFORE`) so the clipboard is not empty.
3. **Hold Right Ctrl**, say a clear sentence: *The quick brown fox jumps over the lazy dog.*
4. **Release** Right Ctrl.
5. Tray should go Recording → Transcribing → Idle (vulkan).
6. **Pass:** the sentence (or a close transcript) appears at the caret.
7. **Pass:** paste with Ctrl+V in another Notepad — you get `CLIPBOARD-BEFORE`, not the transcript.

### B. Accidental tap

1. Click into Notepad.
2. Tap Right Ctrl and release immediately (under ~200 ms), do not speak.
3. **Pass:** nothing new is pasted.

### C. Silence

1. Hold Right Ctrl for a second in a quiet room, release.
2. **Pass:** nothing pasted (no “thanks”, “you”, or “Thank you for watching”).

### D. Modifier leak (the point of swallowing Right Ctrl)

1. Open Notepad, type `hello`, leave the caret in the window.
2. Hold **Right Ctrl** and while holding it tap **S**.
3. **Pass:** Notepad does **not** open Save. You may see a letter `s` or nothing; you must not get a Save dialog.
4. Release Right Ctrl.
5. Hold **Left Ctrl** and press **S**.
6. **Pass:** Save dialog still appears. Cancel it.

### E. Electron paste race (VS Code)

1. Copy `CLIPBOARD-BEFORE` again.
2. Open this repo in VS Code or Cursor, click in a markdown scratch buffer.
3. Hold Right Ctrl, say *paste check in electron*, release.
4. **Pass:** that phrase lands in the editor, **not** `CLIPBOARD-BEFORE`.
5. **Pass:** Ctrl+V afterwards still pastes `CLIPBOARD-BEFORE`.

### F. Shared microphone

1. Join a Discord or Zoom call (or open the voice settings and watch the input meter).
2. Hold Right Ctrl and speak a short phrase into Notepad.
3. **Pass:** the call still sees your mic (no exclusive-mode steal) and dictation still transcribes.

### G. First syllable / last syllable

1. Hold Right Ctrl and immediately say *hello* (do not pause after the key).
2. **Pass:** transcript includes “hello”, not “ello”.
3. Hold Right Ctrl, say *cat*, release the key the instant you finish the T.
4. **Pass:** transcript is “cat” (or similar), not “ca”.

### H. Re-entrancy

1. Hold Right Ctrl, speak, release.
2. Immediately hold Right Ctrl again while the tray still says Transcribing.
3. **Pass:** the second press is ignored until Idle; you do not get overlapped garbage.

### I. Elevated window (optional)

1. Open Notepad **as Administrator**.
2. From a normal (non-admin) dictation process, try to dictate into it.
3. **Pass:** paste fails or does nothing. This is expected UIPI. Dictate into a normal window instead, or run dictation elevated if you truly need admin targets.

### J. Quit

1. Tray → **Quit**.
2. **Pass:** icon disappears, Right Ctrl is a normal modifier again, Discord still has the mic.

## 4. If something fails

| Symptom | Where to look |
| --- | --- |
| No tray icon | Terminal output; run from an activated venv |
| Idle (cpu) on the 7900 XTX | `dictation.log` — Vulkan device list; AMD drivers |
| Downloading stuck | Network; delete `%APPDATA%\Dictation\models\*.part` and retry |
| Permission / no audio | Windows microphone privacy; correct default input device |
| Ctrl+S while talking | Hook not installed — only one dictation instance; run `--check` |
| Old clipboard pasted into Slack/VS Code | File a note with the log; WM_PASTE path failed and Ctrl+V raced |
| Nothing pastes into admin Notepad | Expected without elevation |

Logs: `%APPDATA%\Dictation\dictation.log`
Config: `%APPDATA%\Dictation\config.json`
