# Windows local dictation

Hold **Right Ctrl** to record from the default microphone. Release to transcribe locally with whisper.cpp and paste into the focused window. The app lives in the system tray. There are no API keys.

This is a personal Windows utility. The microphone stays open in **WASAPI shared** mode while the tray icon is running so the first syllable is not clipped.

## Requirements

- Windows 10/11 (64-bit)
- Python 3.11+ (`winget install Python.Python.3.12`)
- [Microsoft Visual C++ 2015–2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) (`winget install Microsoft.VCRedist.2015+.x64`)
- A microphone enabled under Windows **Settings → Privacy & security → Microphone** (allow desktop apps)
- For GPU transcription: modern AMD/NVIDIA/Intel graphics drivers with **Vulkan** support

> [!NOTE]
> On first run, the app automatically downloads the Vulkan `whisper.cpp` engine (~18 MB) and the `ggml-large-v3-turbo` model (~1.6 GB) into `%APPDATA%\Dictation\`.

---

## Quick Install

Open **PowerShell** in the project directory:

```powershell
# 1. (Optional) If Python or VC++ Redistributable is missing:
winget install Python.Python.3.12 --scope user
winget install Microsoft.VCRedist.2015+.x64

# 2. Allow PowerShell script execution for this session:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Create and activate virtual environment:
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 4. Install package:
pip install -e .

# 5. Smoke-test audio and keyboard hook (no model download):
python -m dictation --check

# 6. Start dictation:
python -m dictation
```

*(Optional: install into a dedicated venv you keep on PATH, rather than your global interpreter)*.

---

## Usage

1. Focus Notepad, VS Code, Discord, Slack, or any window that accepts text.
2. **Hold Right Ctrl** and speak naturally (or **double-tap** Right Ctrl / tray **Continuous Mode** for hands-free).
3. **Release Right Ctrl** (or single-tap / toggle Continuous Mode off) — after a short transcription delay, text appears at the caret, with a trailing space so the next utterance continues the sentence.
4. Tray tooltip shows `Idle (vulkan)` / `Recording 42%` / `Recording (continuous)` / `Transcribing…` (or `Muted`). A floating pill at the bottom of the screen mirrors recording / transcribing / success. Right-click the tray icon to switch microphones live, toggle continuous mode, copy recent transcripts, mute dictation, toggle sound effects, or access configuration and logs.

**Key behavior:**
- Right Ctrl is **swallowed** while held so it never reaches other programs. Typing S or W while talking will not trigger Save or Close Tab.
- **Left Ctrl is untouched** — `Left Ctrl + S` still saves normally.
- **Cancel take:** Press **Escape** while recording (holding Right Ctrl, or during continuous mode) to abort immediately without transcribing or pasting.
- **Mute Dictation:** Temporarily disables hotkey recording for the current session (session-only; not persisted across app restarts).
- **Recent Transcripts:** Clicking an entry in the Recent Transcripts submenu copies the text directly to your clipboard (overwriting current clipboard contents).
- Accidental taps shorter than ~200 ms, or near-silent audio takes, are automatically ignored.
- Continuous mode auto-stops after `continuous_max_seconds` (default 120).
- If paste is blocked (elevated window / UIPI), tray shows `Paste failed — use Recent Transcripts` and the take is still saved under Recent Transcripts.

---

## Testing

To run the automated test suite:

```powershell
pip install -e ".[test]"
pytest -v
```

See [TESTING.md](TESTING.md) for the manual hardware checklist and test breakdown.


---

## How paste works

Unicode `SendInput` is the primary path (typing characters directly at the caret, in 20-code-unit chunks). Your clipboard is **not touched or overwritten** on the happy path. If `SendInput` fails or is blocked, it falls back to snapshotting the previous clipboard, setting the transcript, sending `SendMessageTimeout(WM_PASTE)` or `Ctrl+V`, and restoring your previous clipboard in a `finally` block.

---

## Config

`%APPDATA%\Dictation\config.json` is created on first run. Useful keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `language` | `en` | Whisper language code (`en`, `de`, `fr`, `es`, etc.) |
| `device` | `null` | WASAPI input index, or default microphone |
| `preroll_ms` | `350` | Audio kept from before key-down (covers hold classification delay) |
| `suffix_ms` | `80` | Extra audio captured after key-up |
| `max_record_seconds` | `60` | Auto-release watchdog if key hold exceeds this duration |
| `continuous_max_seconds` | `120` | Auto-stop watchdog for hands-free continuous mode |
| `hold_ms` | `250` | Hold threshold before Right Ctrl starts push-to-talk |
| `double_tap_ms` | `350` | Window for double-tap → continuous mode |
| `hud_enabled` | `true` | Show the floating bottom-center status pill |
| `energy_threshold` | `0.008` | RMS energy floor to drop silent takes |
| `model_filename` | `ggml-large-v3-turbo.bin` | ggml file under `models\` |
| `sound_effects` | `true` | Subtle audio cues (earcons) on start, stop, paste, and discard |

Names and jargon live in `%APPDATA%\Dictation\vocabulary.json` (created on first use):

```json
{
  "words": ["Dictation", "Cursor", "Vulkan"],
  "replacements": [
    {"heard": "wisper", "meant": "Whisper"}
  ]
}
```

`words` and replacement targets are fed to Whisper as an `initial_prompt`. After transcription, `replacements` are applied as whole-word, case-insensitive substitutions. Successful pastes are appended to `%APPDATA%\Dictation\history.json` (last 200).

To time the engine without the hotkey or paste path:

```powershell
python -m dictation --transcribe C:\path\to\clip.wav
```

Logs: `%APPDATA%\Dictation\dictation.log`. First launch can sit on **Warming up GPU** for a minute while Vulkan shaders compile.

---

## Conflicts & Limits

- **VirtualBox:** The default host key is Right Ctrl. Change the host key in VirtualBox preferences to avoid conflicts.
- **RDP:** Run dictation in the session that owns the keyboard hook.
- **Elevated / Admin Windows:** Standard user processes cannot send keystrokes to elevated Administrator windows (UIPI). Run dictation as Administrator only if you need to dictate into admin consoles.
- **Always-on Mic:** WASAPI capture stays open in **shared mode** while the tray icon exists to provide pre-roll. Other apps like Discord and Zoom can use the microphone simultaneously.

---

## Troubleshooting & Common Setup Errors

| Symptom / Error | Cause | Solution |
| :--- | :--- | :--- |
| `Python was not found...` | Windows Store app execution alias intercepted `python` | Install Python via `winget install Python.Python.3.12 --scope user` or disable aliases in *Settings → Apps → Advanced app settings → App execution aliases*. |
| `FileNotFoundError: Could not find module ... whisper.dll (or one of its dependencies)` | Missing `VCOMP140.DLL` (Visual C++ OpenMP runtime) | Run `winget install Microsoft.VCRedist.2015+.x64`, click **Yes** on the UAC prompt, and restart `python -m dictation`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | PowerShell default script execution policy | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` before activating `.venv`. |
| `No module named dictation` | Running global Python instead of the virtual environment | Run `.\.venv\Scripts\Activate.ps1` first, or run `pip install -e .` in your global Python. |
| Tray tooltip says `Idle (cpu)` instead of `vulkan` | Missing Vulkan runtime / outdated graphics drivers | Update graphics drivers (AMD Adrenalin, NVIDIA GeForce, or Intel Arc). Verify Vulkan with `vulkaninfo`. |
| `WASAPI host API not found` / No audio captured | Microphone privacy disabled or no default device | Enable microphone in Windows Settings under *Privacy & security → Microphone*, and verify your default device in Sound Settings. |

