import concurrent.futures
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store, Conflict
from app import serve
from connect_ai import install
from mcp_server import call

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.s=Store(self.root/'vault')
    def tearDown(self): self.tmp.cleanup()
    def save(self,style='cash-grab',category='art',text='Round shapes',game_id=''):
        n=self.s.read_note(style,category,game_id)
        return self.s.save_note(style,category,text,n['revision'],game_id)
    def test_style_isolation_and_persistence(self):
        self.save()
        other=Store(self.root/'vault')
        self.assertEqual(other.read_note('cash-grab','art')['text'],'Round shapes')
        self.assertEqual(other.read_note('serious-game','art')['text'],'')
    def test_conflict_and_history(self):
        old=self.s.read_note('cash-grab','art')
        self.save(text='First')
        with self.assertRaises(Conflict): self.s.save_note('cash-grab','art','Overwrite',old['revision'])
        self.save(text='Second')
        self.assertEqual(next((self.s.root/'history').rglob('*.md')).read_text(),'First')
    def test_concurrent_writers(self):
        old=self.s.read_note('cash-grab','art')
        def work(text):
            try:
                Store(self.root/'vault').save_note('cash-grab','art',text,old['revision'])
                return True
            except Conflict:return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(work,['A','B'])),1)
    def test_game_exceptions_and_context_budget(self):
        g=self.s.save_game('Example','cash-grab')
        self.save(text='Shared blue palette')
        self.save(text='Use red for this game',game_id=g['id'])
        c=self.s.context('cash-grab',['art'],g['id'],max_chars=500)
        self.assertIn('Use red',c['text']);self.assertIn('Shared blue',c['text'])
        self.assertLessEqual(c['characters'],500)
        with self.assertRaises(ValueError): self.s.context('serious-game',game_id=g['id'])
        self.save(text='X'*1000)
        c=self.s.context('cash-grab',['art'],max_chars=500)
        self.assertTrue(c['truncated']);self.assertLessEqual(c['characters'],500)
    def test_external_edit_progress(self):
        self.s.state()
        n=self.s.read_note('cash-grab','art')
        Path(n['path']).write_text('External preference')
        changes=self.s.changes()
        self.assertEqual(changes['events'][-1]['actor'],'External editor')
        self.assertEqual(self.s.state()['notes'][0]['text'],'External preference')
        self.assertEqual(len(self.s.changes()['events']),1)
    def test_reference_boundary_and_unchanged_original(self):
        refs=self.root/'refs';refs.mkdir();(refs/'readme.txt').write_text('reference')
        outside=self.root/'secret.txt';outside.write_text('outside')
        (refs/'escape').symlink_to(outside)
        r=self.s.add_reference('Library','cash-grab','art',str(refs))
        with self.assertRaises(ValueError):self.s.reference_path(r['id'],'../secret.txt')
        with self.assertRaises(ValueError):self.s.reference_path(r['id'],'escape')
        result=self.s.browse(r['id'])
        self.assertEqual([x['name'] for x in result['items']],['readme.txt'])
        self.s.remove_reference(r['id'],r['revision'])
        self.assertEqual((refs/'readme.txt').read_text(),'reference')
    def test_task_handoff_conflict_and_changes_cursor(self):
        t=call(self.s,'create_task',{'title':'Shop','style':'cash-grab','objective':'Build a shop','owner':'Codex'},'Claude Desktop')
        t2=call(self.s,'update_task',{'id':t['id'],'revision':t['revision'],'status':'Ready for review','owner':'Claude Desktop','result':'Implemented and checked'},'Codex')
        with self.assertRaises(Conflict):self.s.update_task(t['id'],1,'Done','You','Old')
        seen=call(self.s,'read_task',{'id':t['id']},'Claude Desktop')
        self.assertEqual(seen['result'],'Implemented and checked')
        c=self.s.changes(limit=1);self.assertTrue(c['has_more'])
        self.assertEqual(len(self.s.changes(since=c['cursor'])['events']),1)
        self.assertEqual(len(self.s.changes(since=self.s.changes()['cursor'])['events']),0)
    def test_config_merge_preserves_unrelated_settings(self):
        home=self.root/'home';claude=home/'Library/Application Support/Claude/claude_desktop_config.json';claude.parent.mkdir(parents=True)
        claude.write_text(json.dumps({'theme':'dark','mcpServers':{'existing':{'command':'keep'}}}))
        codex=home/'.codex/config.toml';codex.parent.mkdir();codex.write_text('model = "keep-model"\n[mcp_servers.existing]\ncommand = "keep"\n')
        result=install(home,self.s.root)
        self.assertEqual(len(result['backups']),2)
        self.assertEqual(json.loads(claude.read_text())['mcpServers']['existing']['command'],'keep')
        self.assertIn('model = "keep-model"',codex.read_text())
        install(home,self.s.root)
        self.assertEqual(codex.read_text().count('[mcp_servers.conectify]'),1)
    def test_stdio_protocol_and_cross_process(self):
        script=str(Path(__file__).resolve().parents[1]/'mcp_server.py')
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','clientInfo':{'name':'test','version':'1'}}}, {'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list'}, {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'create_task','arguments':{'title':'Cross process','style':'serious-game','objective':'Check persistence'}}}]
        proc=subprocess.run([sys.executable,'-B',script,'--vault',str(self.s.root),'--client','Claude Desktop'],input='\n'.join(map(json.dumps,requests))+'\n',text=True,capture_output=True,check=True)
        responses=[json.loads(x) for x in proc.stdout.splitlines()]
        self.assertEqual(len(responses),3);self.assertEqual(len(responses[1]['result']['tools']),12)
        task=json.loads(responses[2]['result']['content'][0]['text'])
        self.assertEqual(self.s.task(task['id'])['title'],'Cross process')
    def test_screenshot_scope_image_and_learning_handoff(self):
        png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7V8AAAAASUVORK5CYII='
        game=self.s.save_game('Screenshot game','cash-grab')
        upload=self.s.attach_screenshot('../example.png',png,'cash-grab','ui','Only button shapes',game['id'])
        ref=upload['reference']; task=upload['task']
        self.assertEqual(ref['title'],'example.png')
        self.assertEqual(task['owner'],'Codex')
        self.assertEqual(task['game_id'],game['id'])
        self.assertIn('Only button shapes',task['objective'])
        self.assertIn('cannot reveal animation timing',task['objective'])
        self.assertEqual(self.s.read_note('cash-grab','ui',game['id'])['text'],'')
        self.assertNotIn(ref['id'],self.s.context('cash-grab')['text'])
        self.assertIn(ref['id'],self.s.context('cash-grab',game_id=game['id'])['text'])
        shared=call(self.s,'list_references',{'style':'cash-grab'},'Test Codex')
        self.assertEqual(shared['items'],[])
        result=call(self.s,'read_reference',{'id':ref['id']},'Test Codex')
        self.assertEqual(result['mimeType'],'image/png')
        self.assertEqual(result['_image'],png)
        note=call(self.s,'read_note',{'style':'cash-grab','category':'ui','game_id':game['id']},'Test Codex')
        call(self.s,'save_note',{'style':'cash-grab','category':'ui','game_id':game['id'],'revision':note['revision'],'text':'Test-only extracted preference.'},'Test Codex')
        call(self.s,'update_task',{'id':task['id'],'revision':task['revision'],'status':'Done','owner':'Codex','result':'Saved test preference.'},'Test Codex')
        self.assertEqual(self.s.task(task['id'])['status'],'Done')
        self.assertEqual(self.s.read_note('cash-grab','ui')['text'],'')

    def test_screenshot_rejects_bad_images_and_invalid_scope(self):
        import base64
        for image in ['not base64',base64.b64encode(b'<html>not an image</html>').decode(),'A'*5600001]:
            with self.assertRaises(ValueError):self.s.attach_screenshot('bad.png',image,'cash-grab','art')
        self.assertEqual(self.s.list_records('refs'),[])
        self.assertEqual(self.s.list_records('tasks'),[])

    def test_host_origin_csrf_export_and_range(self):
        server=serve(self.s.root,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            self.assertIn(b'Conectify',urlopen(base).read())
            state=json.loads(urlopen(base+'/api/state').read())
            with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/state',headers={'Host':'evil.example'}))
            self.assertEqual(e.exception.code,403)
            with self.assertRaises(HTTPError):urlopen(Request(base+'/api/state',headers={'Origin':'https://evil.example'}))
            with self.assertRaises(HTTPError):urlopen(Request(base+'/api/game',data=b'{}',headers={'Content-Type':'application/json'}))
            request=Request(base+'/api/game',data=json.dumps({'name':'HTTP game','style':'cash-grab'}).encode(),headers={'Content-Type':'application/json','X-Conectify-Token':state['token']})
            self.assertEqual(json.loads(urlopen(request).read())['name'],'HTTP game')
            shot=self.s.attach_screenshot('backup.png','iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7V8AAAAASUVORK5CYII=','cash-grab','art')
            backup=zipfile.ZipFile(io.BytesIO(urlopen(base+'/api/export').read()))
            self.assertIn('conectify.sqlite3',backup.namelist())
            self.assertIn('attachments/'+Path(shot['reference']['path']).name,backup.namelist())
            self.assertIn('styles/cash-grab/art.md',backup.namelist())
            ref=self.root/'sample.txt';ref.write_text('abcdefghij');r=self.s.add_reference('test','cash-grab','art',str(ref))
            response=urlopen(Request(base+'/api/media?id='+r['id'],headers={'Range':'bytes=2-5'}))
            self.assertEqual(response.status,206);self.assertEqual(response.read(),b'cdef')
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main(verbosity=2)
