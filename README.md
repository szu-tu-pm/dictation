# Windows local dictation

Hold **Right Ctrl** to record from the default microphone. Release to transcribe locally with whisper.cpp and paste into the focused window. The app lives in the system tray. There are no API keys.

This is a personal Windows utility. The microphone stays open in **WASAPI shared** mode while the tray icon is running so the first syllable is not clipped.

## Requirements

- Windows 10/11, Python 3.11+
- A microphone allowed for Python / Terminal under **Settings → Privacy → Microphone**
- For GPU transcription: current AMD/NVIDIA/Intel drivers with **Vulkan** (this box: Radeon RX 7900 XTX)

First run downloads a Vulkan `whisper.cpp` build (~18 MB) and `ggml-large-v3-turbo` (~1.6 GB) into `%APPDATA%\Dictation\`.

## Install

```powershell
cd path\to\dictation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python -m dictation --check
python -m dictation
```

`--check` confirms WASAPI capture and that the Right Ctrl hook can be installed. It does not download the model.

## Usage

1. Focus Notepad (or any window that accepts paste).
2. **Hold Right Ctrl** and speak.
3. Release. After transcription the text is inserted at the caret.
4. Tray tooltip shows Idle / Recording / Transcribing. **Quit** stops the app.

Right Ctrl is **swallowed** so it never reaches other programs. Brushing S or W while talking will not fire Save or Close Tab. **Left Ctrl is unchanged** — Left Ctrl+S still saves.

Accidental taps shorter than ~200 ms, or near-silent captures, are ignored.

## Conflicts and limits

- **VirtualBox:** the default host key is Right Ctrl. Change that host key in VirtualBox, or this app and the VM will fight.
- **RDP:** dictate in the session that owns the hook. If dictation runs on the host, swallowed Right Ctrl will not reach the remote desktop.
- **Elevated windows:** a non-elevated process cannot paste into an admin window (UIPI). Run dictation elevated only if you need that, or paste into a normal window.
- **Always-on mic:** capture runs for as long as the tray icon exists. That is required for pre-roll. Quit the app to release the device. Shared WASAPI should still let Discord or Zoom use the same mic.

## How paste works

Unicode `SendInput` is tried first (no clipboard). If that returns zero events or fails, the previous clipboard is snapshotted, the transcript is set, then `SendMessageTimeout(WM_PASTE)` is sent to the focused control. If `WM_PASTE` fails, Ctrl+V is used. The clipboard snapshot is restored in a `finally` block after the clipboard path.

## Config

`%APPDATA%\Dictation\config.json` is created on first run. Useful keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `language` | `en` | Whisper language |
| `device` | `null` | WASAPI input index, or default |
| `preroll_ms` | `200` | Audio kept from before key-down |
| `suffix_ms` | `80` | Extra audio after key-up |
| `max_record_seconds` | `60` | Auto-release if hold exceeds this |
| `energy_threshold` | `0.008` | Drop near-silent takes |
| `model_filename` | `ggml-large-v3-turbo.bin` | ggml file under `models\` |

Logs: `%APPDATA%\Dictation\dictation.log`. The tray status string includes `vulkan` or `cpu` after the model loads. On this AMD GPU it should say **Idle (vulkan)**.

## Verification

- Hold Right Ctrl in Notepad, speak a sentence, confirm the text appears, confirm a short tap does not paste junk.
- Confirm Right Ctrl does **not** trigger Ctrl+S while talking; Left Ctrl+S still saves.
- Confirm Discord/Zoom can use the mic at the same time.
- Confirm the tray tooltip shows **vulkan** (not cpu) on a 7900 XTX.
- Paste into a sluggish Electron app (VS Code or Slack) and confirm the transcript lands.
