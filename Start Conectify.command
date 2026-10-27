#!/bin/zsh
cd -- "${0:A:h}"
export PYTHONDONTWRITEBYTECODE=1
exec /usr/bin/python3 -B desktop.py
