#!/usr/bin/env python3
"""Conectify localhost application. Run with Python 3.9+."""
import argparse
import io
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import webbrowser
import zipfile
from core import Store, Conflict

BASE=Path(__file__).resolve().parent
TOKEN=secrets.token_urlsafe(32)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):
        # Keep idle polling from growing the log indefinitely.
        if len(args)>1 and str(args[1]).isdigit() and int(args[1])<400:
            return
        super().log_message(fmt,*args)

    @property
    def store(self): return self.server.store

    def allowed(self):
        host=self.headers.get('Host','')
        port=self.server.server_port
        if host not in ('127.0.0.1:%s'%port,'localhost:%s'%port): return False
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:%s'%port,'http://localhost:%s'%port): return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site': return False
        return True

    def send(self,data,status=200,mime='application/json; charset=utf-8',extra=None):
        if isinstance(data,(dict,list)): data=json.dumps(data,ensure_ascii=False).encode()
        if isinstance(data,str): data=data.encode()
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError): pass

    def do_GET(self):
        if not self.allowed(): return self.send({'error':'Local access only.'},403)
        url=urlsplit(self.path); q={k:v[0] for k,v in parse_qs(url.query).items()}
        try:
            if url.path=='/api/health': return self.send({'app':'conectify','version':'1.0.0','vault':str(self.store.root)})
            if url.path=='/api/state':
                state=self.store.state()
                if q.get('version')==state['version']: return self.send({'unchanged':True})
                state['token']=TOKEN
                return self.send(state)
            if url.path=='/api/config': return self.send(config(self.store))
            if url.path=='/api/browse': return self.send(self.store.browse(**q))
            if url.path=='/api/context':
                if q.get('categories'): q['categories']=q['categories'].split(',')
                return self.send(self.store.context(**q))
            if url.path=='/api/media':
                p=self.store.reference_path(q.get('id',''),q.get('relative',''))
                if not p.is_file(): raise ValueError('Not a file.')
                mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
                inline=mime in ('image/png','image/jpeg','image/webp','image/gif','video/mp4','video/webm','audio/mpeg','audio/wav')
                size=p.stat().st_size
                # Stream large references instead of reading whole videos into RAM.
                start,end=0,max(size-1,0); partial=False
                range_header=self.headers.get('Range','')
                if range_header.startswith('bytes=') and ',' not in range_header:
                    parts=range_header[6:].split('-',1)
                    if parts[0]:
                        start=int(parts[0]); end=min(int(parts[1]) if parts[1] else end,end)
                    elif parts[1]: start=max(0,size-int(parts[1]))
                    if start>end or start>=size: return self.send({'error':'Invalid range'},416)
                    partial=True
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type',mime if inline else 'application/octet-stream')
                self.send_header('Content-Length',str(end-start+1 if size else 0))
                self.send_header('Accept-Ranges','bytes')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'none'; sandbox")
                self.send_header('Content-Disposition','inline' if inline else 'attachment')
                if partial: self.send_header('Content-Range','bytes %s-%s/%s'%(start,end,size))
                self.end_headers()
                with p.open('rb') as f:
                    f.seek(start); left=end-start+1 if size else 0
                    while left:
                        chunk=f.read(min(left,65536))
                        if not chunk: break
                        self.wfile.write(chunk); left-=len(chunk)
                return
            if url.path=='/api/export':
                memory=io.BytesIO()
                with self.store.lock():
                    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as z:
                        state=self.store.state()
                        z.writestr('manifest.json',json.dumps(state,indent=2,ensure_ascii=False))
                        for note in state['notes']:
                            z.writestr(str(Path(note['path']).relative_to(self.store.root)),note['text'])
                        for p in (self.store.root/'attachments').glob('*') if (self.store.root/'attachments').exists() else []:
                            if p.is_file() and not p.is_symlink():
                                z.write(p,str(p.relative_to(self.store.root)))
                        # SQLite backup API captures a consistent database including WAL.
                        import tempfile
                        with tempfile.TemporaryDirectory() as tmp:
                            backup=Path(tmp)/'conectify.sqlite3'
                            with self.store.db() as source:
                                with sqlite3.connect(str(backup)) as target: source.backup(target)
                            z.write(backup,'conectify.sqlite3')
                        for p in (self.store.root/'history').rglob('*.md') if (self.store.root/'history').exists() else []:
                            z.write(p,str(p.relative_to(self.store.root)))
                return self.send(memory.getvalue(),mime='application/zip',extra={'Content-Disposition':'attachment; filename="conectify-backup.zip"'})
            files={'/':'index.html','/style.css':'style.css','/app.js':'app.js','/logo.svg':'logo.svg'}
            if url.path not in files: return self.send({'error':'Not found'},404)
            p=BASE/'static'/files[url.path]
            return self.send(p.read_bytes(),mime=mimetypes.guess_type(p.name)[0] or 'text/plain')
        except (BrokenPipeError,ConnectionResetError): pass
        except (ValueError,OSError,TypeError) as e: self.send({'error':str(e)},400)

    def do_POST(self):
        if not self.allowed() or not secrets.compare_digest(self.headers.get('X-Conectify-Token',''),TOKEN):
            return self.send({'error':'Reload Conectify to refresh your local session.'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            limit=6*1024*1024 if urlsplit(self.path).path=='/api/screenshot' else 1024*1024
            if length<0 or length>limit: raise ValueError('Request too large.')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('Expected an object.')
            routes={'/api/note':self.store.save_note,'/api/game':self.store.save_game,'/api/reference':self.store.add_reference,
                    '/api/reference/update':self.store.update_reference,'/api/reference/remove':self.store.remove_reference,
                    '/api/screenshot':self.store.attach_screenshot,'/api/task':self.store.create_task,'/api/task/update':self.store.update_task}
            path=urlsplit(self.path).path
            if path in routes: return self.send(routes[path](**data))
            if path=='/api/connect':
                if getattr(sys, 'frozen', False) and sys.executable.startswith('/Volumes/'):
                    raise ValueError('Drag Conectify to Applications, eject the installer, and open the installed app before connecting your AIs.')
                from connect_ai import install
                return self.send(install(Path.home(), self.store.root))
            if path=='/api/pick':
                if sys.platform!='darwin': raise ValueError('Paste a local path on this operating system.')
                kind=data.get('kind','file')
                script='POSIX path of (choose folder with prompt "Choose a Conectify reference folder")' if kind=='folder' else 'POSIX path of (choose file with prompt "Choose a Conectify reference")'
                result=subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,text=True,timeout=120)
                return self.send({'path':result.stdout.strip(),'cancelled':result.returncode!=0})
            if path=='/api/reveal':
                p=self.store.reference_path(data['id'],data.get('relative',''))
                if sys.platform=='darwin': subprocess.Popen(['/usr/bin/open','-R',str(p)])
                else: raise ValueError('Open this reference using its displayed local path.')
                return self.send({'revealed':True})
            return self.send({'error':'Not found'},404)
        except Conflict as e: self.send({'error':str(e),'conflict':True},409)
        except (ValueError,OSError,TypeError,KeyError,subprocess.TimeoutExpired) as e: self.send({'error':str(e)},400)


def config(store):
    command=sys.executable
    script='--mcp' if getattr(sys, 'frozen', False) else str(BASE/'mcp_server.py')
    vault=str(store.root)
    claude={'mcpServers':{'conectify':{'command':command,'args':[script,'--vault',vault,'--client','Claude Desktop']}}}
    codex='[mcp_servers.conectify]\ncommand = '+json.dumps(command)+'\nargs = '+json.dumps([script,'--vault',vault,'--client','Codex'])+'\n'
    return {'claude':json.dumps(claude,indent=2),'codex':codex,'vault':vault,'instructions':'Use Conectify to read the correct game style before working. Fetch only relevant categories. Read shared tasks and changes when resuming. Record meaningful progress and results. Save permanent preferences only when I explicitly ask you to remember them. Never automatically poll or assume another agent has seen an update.'}

def serve(vault,port):
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.store=Store(vault)
    return server

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--vault',default=str(BASE/'vault'))
    parser.add_argument('--port',type=int,default=4317)
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    try: server=serve(args.vault,args.port)
    except OSError:
        print('Port %s is occupied. If Conectify is running, open http://127.0.0.1:%s; otherwise choose --port 4318.'%(args.port,args.port),file=sys.stderr)
        sys.exit(1)
    url='http://127.0.0.1:%s'%server.server_port
    print('Conectify is ready at '+url,flush=True)
    if args.open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
