"""Standalone entry point: Finder launcher, HTTP service, and stdio MCP."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from http.client import HTTPConnection
import webbrowser
from core import Store
from app import serve
from mcp_server import run
from migrate_vault import migrate


def default_vault():
    return Path.home() / 'Library/Application Support/Conectify/vault'


def import_previous_vault(vault):
    """On first launch, retain the vault already connected to Claude Desktop."""
    if vault.exists():
        return
    settings = Path.home() / 'Library/Application Support/Claude/claude_desktop_config.json'
    try:
        entry = json.loads(settings.read_text()).get('mcpServers', {}).get('conectify', {})
        args = entry.get('args', [])
        source = Path(args[args.index('--vault') + 1]).expanduser().resolve()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return
    if source != vault and (source / 'conectify.sqlite3').is_file():
        migrate(source, vault)


def health(port, vault):
    # Local IPC must bypass system/network proxy settings.
    connection = HTTPConnection('127.0.0.1', port, timeout=.5)
    try:
        connection.request('GET', '/api/health')
        response = connection.getresponse()
        data = json.loads(response.read())
        return response.status == 200 and data.get('app') == 'conectify' and data.get('vault') == str(vault)
    except Exception:
        return False
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url-only', action='store_true')
    parser.add_argument('--mcp', action='store_true')
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--vault', default=str(default_vault()))
    parser.add_argument('--port', type=int, default=4317)
    parser.add_argument('--client', default='MCP client')
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    if vault == default_vault().resolve():
        import_previous_vault(vault)
    if args.mcp:
        run(Store(vault), args.client)
        return 0
    if args.serve:
        try:
            server = serve(vault, args.port)
        except OSError as error:
            # A windowed PyInstaller exception opens a modal crash dialog, which
            # prevents the launcher from observing exit and trying another port.
            print('Conectify server could not start: ' + str(error), file=sys.stderr)
            return 1
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return 0
    # Prefer the normal port, but never reopen another vault's server.
    ports = range(args.port, args.port + 10)
    for port in ports:
        if health(port, vault):
            if args.url_only: print('http://127.0.0.1:%d' % port, flush=True)
            else: webbrowser.open('http://127.0.0.1:%d' % port)
            return 0
    vault.mkdir(parents=True, exist_ok=True)
    for port in ports:
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command += [str(Path(__file__).resolve())]
        with (vault / 'server.log').open('a') as log:
            process = subprocess.Popen(command + ['--serve', '--vault', str(vault), '--port', str(port)],
                stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
                env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
        for _ in range(50):
            if health(port, vault):
                if args.url_only: print('http://127.0.0.1:%d' % port, flush=True)
                else: webbrowser.open('http://127.0.0.1:%d' % port)
                return 0
            if process.poll() is not None:
                break
            time.sleep(.1)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
    raise RuntimeError('Conectify could not start. See ' + str(vault / 'server.log'))

if __name__ == '__main__':
    sys.exit(main())
