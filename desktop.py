#!/usr/bin/env python3
"""Launch or reopen Conectify without keeping a Terminal window running."""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

BASE=Path(__file__).resolve().parent

def running(port):
    try:
        with urlopen('http://127.0.0.1:%d/api/health'%port,timeout=.5) as r:
            result=json.load(r)
            return result.get('app')=='conectify' and result.get('vault')==str(BASE/'vault')
    except Exception:
        return False

def main():
    port=4317
    if not running(port):
        (BASE/'vault').mkdir(exist_ok=True)
        with (BASE/'vault'/'server.log').open('a') as log:
            subprocess.Popen([sys.executable,'-B',str(BASE/'app.py'),'--port',str(port)],cwd=str(BASE),stdout=log,stderr=log,start_new_session=True)
        for _ in range(40):
            if running(port): break
            time.sleep(.15)
        else:
            print('Conectify could not start. Check vault/server.log; port 4317 may be in use.',file=sys.stderr)
            return 1
    webbrowser.open('http://127.0.0.1:%d'%port)
    return 0

if __name__=='__main__':sys.exit(main())
