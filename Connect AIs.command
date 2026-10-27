#!/bin/zsh
cd -- "${0:A:h}"
export PYTHONDONTWRITEBYTECODE=1
/usr/bin/python3 -B connect_ai.py
printf '\nIf successful, fully quit and reopen Claude Desktop and Codex to load Conectify.\nPress Enter to close.\n'
read
