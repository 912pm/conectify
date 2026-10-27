#!/usr/bin/env python3
"""Conectify MCP tools over newline-delimited JSON-RPC stdio."""
import argparse
import base64
import json
import mimetypes
from pathlib import Path
import sys
from core import Store, STYLES, CATEGORIES

S={'type':'string'}
STYLE={'type':'string','enum':list(STYLES)}
CATEGORY={'type':'string','enum':list(CATEGORIES)}
INT={'type':'integer'}

def tool(name, description, props, required=(), write=False):
    return {'name':name,'description':description,'inputSchema':{'type':'object','properties':props,'required':list(required),'additionalProperties':False},'annotations':{'readOnlyHint':not write,'destructiveHint':False,'openWorldHint':False}}

TOOLS=[
    tool('list_games','List games and their style types. Use the correct style before retrieving context.',{}),
    tool('get_context','Get bounded, relevant style memory. Game exceptions override shared rules. Select only needed categories; no full-vault dump.',{'style':STYLE,'categories':{'type':'array','items':CATEGORY},'game_id':S,'query':S,'max_chars':INT},['style']),
    tool('read_note','Read one style note and its revision. game_id selects game-specific exceptions; omit for shared style.',{'style':STYLE,'category':CATEGORY,'game_id':S},['style','category']),
    tool('save_note','Save a note using its current revision. Only update permanent shared style when the user explicitly asks to remember it. Preserve unrelated rules; read first.',{'style':STYLE,'category':CATEGORY,'text':S,'revision':S,'game_id':S},['style','category','text','revision'],True),
    tool('list_references','List linked reference metadata for one style. Does not analyze or load files.',{'style':STYLE,'category':CATEGORY,'query':S,'offset':INT,'game_id':S},['style']),
    tool('browse_reference','Browse one linked folder level. Filter filenames using query; paginate with offset. No recursive scan.',{'id':S,'relative':S,'query':S,'offset':INT},['id']),
    tool('read_reference','Read a linked text file (bounded excerpt) or small PNG/JPEG/WebP image. Other media returns metadata and a local path. Use only relevant references.',{'id':S,'relative':S,'offset':INT,'max_chars':INT},['id']),
    tool('list_tasks','Read shared work for a style; optionally filter by game or status. Tasks are coordination records, not automatic execution.',{'style':STYLE,'game_id':S,'status':S,'offset':INT},['style']),
    tool('read_task','Read the current task and revision before updating progress.',{'id':S},['id']),
    tool('create_task','Create a shared task or handoff. Include acceptance criteria in objective. Assign owner to Claude, Codex, or You.',{'title':S,'style':STYLE,'objective':S,'game_id':S,'owner':S},['title','style','objective'],True),
    tool('update_task','Record meaningful progress, blocker, result, or handoff. Use latest revision. Include changed files and checks in result. This does not wake the other agent.',{'id':S,'revision':INT,'status':{'type':'string','enum':['To do','Working','Blocked','Ready for review','Done']},'owner':S,'result':S,'message':S},['id','revision','status','owner','result'],True),
    tool('get_changes','Read changes after your saved cursor. Follow has_more until caught up. Check when resuming, not in an autonomous polling loop.',{'since':INT,'style':STYLE,'limit':INT})
]

def validate(name,args):
    definition=next((t for t in TOOLS if t['name']==name),None)
    if not definition: raise ValueError('Unknown tool.')
    schema=definition['inputSchema']
    if not isinstance(args,dict): raise ValueError('Arguments must be an object.')
    if set(args)-set(schema['properties']): raise ValueError('Unknown argument.')
    if set(schema['required'])-set(args): raise ValueError('Missing required argument.')
    for k,v in args.items():
        rule=schema['properties'][k]
        typ=rule['type']
        if (typ=='string' and not isinstance(v,str)) or (typ=='integer' and type(v) is not int) or (typ=='array' and not isinstance(v,list)):
            raise ValueError('Invalid type for '+k)
        if 'enum' in rule and v not in rule['enum']: raise ValueError('Invalid '+k)
    return definition

def call(store,name,args,actor):
    validate(name,args)
    store.touch(actor,name)
    if name=='list_games': return {'styles':STYLES,'games':store.list_records('games')}
    if name=='get_context': return store.context(**args)
    if name=='read_note': return store.read_note(**args)
    if name=='save_note': return store.save_note(actor=actor,**args)
    if name=='list_references':
        rows=store.list_records('refs',args['style'])
        rows=[r for r in rows if (not r.get('game_id') or r['game_id']==args.get('game_id','')) and (not args.get('category') or r['category']==args['category']) and args.get('query','').lower() in (r['title']+' '+r['note']).lower()]
        offset=max(0,args.get('offset',0))
        return {'items':[{**r,'note':r['note'][:500]} for r in rows[offset:offset+30]],'has_more':len(rows)>offset+30,'next_offset':offset+30}
    if name=='browse_reference': return store.browse(**args)
    if name=='read_reference':
        p=store.reference_path(args['id'],args.get('relative',''))
        if not p.is_file(): raise ValueError('Use browse_reference for a folder.')
        mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        size=p.stat().st_size
        if mime in ('image/png','image/jpeg','image/webp') and size <= 4*1024*1024:
            return {'_image':base64.b64encode(p.read_bytes()).decode(),'mimeType':mime}
        if p.suffix.lower() in ('.txt','.md','.lua','.luau','.json','.csv','.toml','.yaml','.yml') or mime.startswith('text/'):
            if size>2*1024*1024: return {'path':str(p),'bytes':size,'message':'Text file exceeds 2 MB; narrow the reference first.'}
            text=p.read_text(encoding='utf-8',errors='replace')
            off=max(0,args.get('offset',0)); count=min(max(1,args.get('max_chars',6000)),20000)
            return {'path':str(p),'text':text[off:off+count],'next_offset':off+count if off+count<len(text) else None}
        return {'path':str(p),'mimeType':mime,'bytes':size,'message':'Open this file in its native application. Media not analyzed.'}
    if name=='list_tasks':
        rows=store.list_records('tasks',args['style'])
        rows=[r for r in rows if (not args.get('game_id') or r['game_id']==args['game_id']) and (not args.get('status') or r['status']==args['status'])]
        offset=max(0,args.get('offset',0))
        return {'items':[{k:r[k] for k in ('id','title','style','game_id','owner','status','revision','updated')} for r in rows[offset:offset+30]],'has_more':len(rows)>offset+30,'next_offset':offset+30}
    if name=='read_task': return store.task(**args)
    if name=='create_task': return store.create_task(actor=actor,**args)
    if name=='update_task': return store.update_task(actor=actor,**args)
    if name=='get_changes': return store.changes(**args)


def run(store,actor):
    initialized=False
    for line in sys.stdin:
        request=None
        try:
            if len(line)>1024*1024: raise ValueError('Request too large.')
            request=json.loads(line)
            if not isinstance(request,dict) or request.get('jsonrpc')!='2.0': raise ValueError('Invalid JSON-RPC request.')
            method=request.get('method')
            if 'id' not in request:
                continue
            if method=='initialize':
                initialized=True
                store.touch(actor,'Connected')
                result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'conectify','version':'1.0.0'},'instructions':'Conectify is shared local design memory and progress. Choose the right style/game. Read targeted context. Check get_changes when resuming. Use revisions for writes. Only save permanent style preferences on explicit user request. Record meaningful progress and handoffs; no automatic polling, agent wakeups, or full-vault dumps.'}
            elif method=='ping': result={}
            elif not initialized:
                raise ValueError('Initialize first.')
            elif method=='tools/list': result={'tools':TOOLS}
            elif method=='tools/call':
                try:
                    params=request.get('params',{})
                    data=call(store,params.get('name'),params.get('arguments',{}),actor)
                    if '_image' in data:
                        result={'content':[{'type':'image','data':data['_image'],'mimeType':data['mimeType']}]}
                    else:
                        result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=False)}]}
                except (ValueError,OSError) as e:
                    result={'content':[{'type':'text','text':str(e)}],'isError':True}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Method not found'}}),flush=True)
                continue
            response={'jsonrpc':'2.0','id':request['id'],'result':result}
        except Exception as e:
            response={'jsonrpc':'2.0','id':request.get('id') if isinstance(request,dict) else None,'error':{'code':-32600,'message':str(e)}}
        print(json.dumps(response,ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--vault',default=str(Path(__file__).resolve().parent/'vault'))
    parser.add_argument('--client',default='MCP client')
    args=parser.parse_args()
    run(Store(args.vault),args.client)
