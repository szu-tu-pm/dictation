#!/usr/bin/env bash
# Cloud Agent bootstrap for the dictation project.
#
# The dictation app itself is Windows-only (WASAPI capture, a global Right-Ctrl
# hook, and whisper.cpp via whisper.dll), so it cannot run on this Linux VM.
# This script prepares the cross-platform automated test suite and pure-logic
# modules so agents can develop and validate changes here.
set -euo pipefail

# python3 -m venv needs ensurepip; libportaudio2 lets sounddevice import for real
# (tests otherwise mock it, but the real import mirrors production more closely).
sudo apt-get update
sudo apt-get install -y --no-install-recommends python3.12-venv libportaudio2

# Isolated venv keeps us clear of PEP 668 "externally-managed" system Python.
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[test]"
