# Testing dictation

Two layers:

1. **Automated** — logic that should not need a microphone (text cleanup, ring buffer, config, zip safety). Run these after every code change.
2. **Manual** — hold-to-talk, paste, Vulkan, and modifier swallowing. The product is a global hook; pytest cannot speak into Notepad for you.

## 0. One-time setup

In PowerShell:

```powershell
cd path\to\dictation

# If Python or VC++ Redistributable is missing:
winget install Python.Python.3.12 --scope user
winget install Microsoft.VCRedist.2015+.x64

# Allow script execution for this session:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Create, activate, and install:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[test]"
```

Allow the microphone:

1. Windows **Settings → Privacy & security → Microphone**
2. Turn **Microphone access** on
3. Allow **Desktop apps** (and Python / Windows Terminal / Cursor if listed)

Plug in or enable the mic you will talk into. Discord/Zoom can stay open; capture is WASAPI **shared**. For setup troubleshooting, see the troubleshooting table in [README.md](README.md#troubleshooting--common-setup-errors).


## 1. Automated suite

```powershell
cd path\to\dictation
.\.venv\Scripts\Activate.ps1

# Run the complete test suite (unit tests and hardware checks)
pytest -v

# Run only pure unit tests (skips tests requiring mic or Windows hardware)
pytest -m "not hardware"

# Run tests with short traceback on failures
pytest -v --tb=short
```

This suite runs quickly and does **not** download the 1.6 GB Whisper model. Test modules:

| Test File | Scope & Logic Verified |
| --- | --- |
| `tests/test_vocabulary.py` | Word list, whole-word replacements, Whisper prompt truncation, JSON roundtrip |
| `tests/test_history.py` | Dictation history prepend, blank skip, 200-item cap |
| `tests/test_text.py` | Filler stripping (`um`, `uh`), ghost transcript filtering (`thanks for watching`), punctuation formatting |
| `tests/test_audio_ring.py` | Circular buffer wrap, sequence preservation, dynamic growth (`grow_to`), truncation counter, RMS & quiet gating |
| `tests/test_config.py` | Config roundtrip save/load, default values, recovery from corrupted JSON and non-dict content |
| `tests/test_paths.py` | Environment variable overrides (`APPDATA`), automatic creation of engine, models, and tmp directories |
| `tests/test_hotkey.py` | `_is_right_ctrl` scancode and extended flag parsing, Left Ctrl isolation, `force_release` state transitions, typematic repeat handling |
| `tests/test_paste.py` | Unicode `SendInput` primary path (no clipboard touches), emoji & surrogate pair support, newline normalization, reachable clipboard fallback |
| `tests/test_app_state.py` | App lifecycle states (`STARTING` -> `IDLE` -> `RECORDING` -> `TRANSCRIBING`), error recovery generation counter, download progress throttling |
| `tests/test_logutil.py` | Logging setup idempotency, formatting, and file handler initialization |
| `tests/test_assets_zip.py` | Zip extraction safety, path traversal (Zip-Slip) rejection, engine readiness detection |
| `tests/test_icons.py` | Tray icon generation across all 6 states (`idle`, `recording`, `transcribing`, etc.) |
| `tests/test_transcribe_helpers.py` | Pointer addresses, Windows short path resolution (`_path_for_fopen`), silence gating |
| `tests/test_hardware.py` | Windows smoke checks: WASAPI default input detection, Right Ctrl hook install/uninstall, clipboard restore, `whisper.dll` ABI struct overlay |

Smoke the same hook/WASAPI path the app uses at startup:

```powershell
python -m dictation --check
```

Time a WAV through Whisper with no hotkey or paste:

```powershell
python -m dictation --transcribe path\to\clip.wav
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
| After load | **Idle (vulkan)** on a Vulkan GPU |

If the tooltip says **Idle (cpu)** or **Error**, open `%APPDATA%\Dictation\dictation.log` and stop. Do not continue the manual list until it says vulkan (or you have knowingly fallen back to CPU).

Quit from the tray when you need to stop. The mic stays open the whole time the icon is visible.

## 3. Manual checklist

Keep the app running. Copy this list and tick as you go.

### A. Happy path (Notepad)

1. Open **Notepad**. Click in the body so the caret is there.
2. Copy some unrelated text (e.g. `CLIPBOARD-BEFORE`) so the clipboard is not empty.
3. **Hold Right Ctrl**, say a clear sentence: *The quick brown fox jumps over the lazy dog.*
4. **Release** Right Ctrl.
5. Tray should go Recording (level % in the tooltip) → Transcribing → Idle (vulkan).
6. **Pass:** the sentence (or a close transcript) appears at the caret.
7. **Pass:** paste with Ctrl+V in another Notepad — you get `CLIPBOARD-BEFORE`, not the transcript (Unicode path leaves clipboard alone; clipboard fallback restores it).

### B. Accidental tap

1. Click into Notepad.
2. Tap Right Ctrl and release immediately (under ~200 ms), do not speak.
3. **Pass:** nothing new is pasted.

### C. Silence

1. Hold Right Ctrl for a second in a quiet room, release.
2. **Pass:** nothing pasted (no “thanks for watching” / “please subscribe” ghosts).

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
| Idle (cpu) on a Vulkan GPU | `dictation.log` — Vulkan device list; GPU drivers |
| Downloading stuck | Network; delete `%APPDATA%\Dictation\models\*.part` and retry |
| Permission / no audio | Windows microphone privacy; correct default input device |
| Ctrl+S while talking | Hook not installed — only one dictation instance; run `--check` |
| Old clipboard pasted into Slack/VS Code | File a note with the log; Unicode path failed and clipboard fallback raced |
| Nothing pastes into admin Notepad | Expected without elevation |
| Tray stuck on Transcribing | First GPU inference compiling shaders; wait, or run `--transcribe` on a WAV |

Logs: `%APPDATA%\Dictation\dictation.log`
Config: `%APPDATA%\Dictation\config.json`
