#!/usr/bin/env python3
"""Merge just Conectify's MCP entry; preserve other settings and back up originals."""
import argparse
import datetime
import json
from pathlib import Path
import re
import shutil
import sys
from app import config, BASE
from core import Store, atomic


def install(home, vault, dry_run=False):
    home=Path(home)
    store=Store(vault)
    conf=config(store)
    claude=home/'Library'/'Application Support'/'Claude'/'claude_desktop_config.json'
    codex=home/'.codex'/'config.toml'
    original=claude.read_text() if claude.exists() else '{}'
    parsed=json.loads(original)
    if not isinstance(parsed,dict): raise ValueError('Claude config is not an object; left unchanged.')
    servers=parsed.setdefault('mcpServers',{})
    if not isinstance(servers,dict): raise ValueError('Claude mcpServers is not an object; left unchanged.')
    entry=json.loads(conf['claude'])['mcpServers']['conectify']
    servers['conectify']=entry
    old=codex.read_text() if codex.exists() else ''
    # Replace only the exact Conectify table, preserving surrounding tables verbatim.
    pattern=r'(?ms)^\[mcp_servers\.conectify\][ \t]*\n.*?(?=^\[|\Z)'
    if re.search(r'(?m)^\[mcp_servers\.conectify\.',old):
        raise ValueError('Conectify has nested TOML settings; merge manually to preserve them.')
    if re.search(r'(?m)^\[mcp_servers\.(?:"conectify"|\'conectify\')\]',old):
        raise ValueError('A quoted Conectify table exists; merge manually to avoid duplicates.')
    new=re.sub(pattern,lambda m:conf['codex']+'\n',old) if re.search(pattern,old) else old.rstrip()+'\n\n'+conf['codex']
    writes=[(claude,json.dumps(parsed,indent=2)+'\n'),(codex,new)]
    # Validate both inputs before any mutation. Never print other configuration values.
    if dry_run:
        return {'would_update':[str(p) for p,_ in writes],'existing_claude_servers':list(servers),'requires_restart':True}
    backups=[]
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for path,text in writes:
        if path.exists():
            backup=path.with_name(path.name+'.conectify-backup-'+stamp)
            shutil.copy2(path,backup)
            backups.append(str(backup))
        atomic(path,text)
        path.chmod(0o600)
    return {'updated':[str(p) for p,_ in writes],'backups':backups,'requires_restart':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',default=str(Path.home()))
    parser.add_argument('--vault',default=str(BASE/'vault'))
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try: print(json.dumps(install(args.home,args.vault,args.dry_run),indent=2))
    except (ValueError,OSError) as e:
        print('Configuration unchanged or incomplete: '+str(e),file=sys.stderr)
        sys.exit(1)
