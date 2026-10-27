"""Real tool implementations. Invoked only after the gateway's verdict."""
import http.client
import ipaddress
import json
import socket
import ssl
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from .policy import safe_path, command_allowed

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=10, context=ssl.create_default_context())
        self.address=address
    def connect(self):
        raw=socket.create_connection((self.address,443),timeout=self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)

def fetch(url, quarantine, cap):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Unsupported URL')
    addresses={entry[4][0] for entry in socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Private, loopback, or reserved network destinations are blocked')
    conn=PinnedHTTPS(parsed.hostname,sorted(addresses)[0])
    try:
        conn.request('GET',parsed.path or '/' if not parsed.query else (parsed.path or '/')+'?'+parsed.query,headers={'User-Agent':'SENTINEL/0.1','Accept-Encoding':'identity'})
        response=conn.getresponse()
        if response.status != 200: raise ValueError(f'HTTP {response.status}; redirects are never followed')
        media=response.getheader('Content-Type','').split(';')[0].strip().lower()
        if media not in {'text/plain','text/html','application/json'}:
            raise ValueError('Only UTF-8 plain text, HTML, and JSON downloads are supported')
        if response.getheader('Content-Encoding','identity') not in {'','identity'}:
            raise ValueError('Compressed responses are not supported')
        body=response.read(cap+1)
        if len(body)>cap: raise ValueError('Download exceeds the byte limit')
        text=body.decode('utf-8')
        if '\x00' in text or text.lstrip().startswith(('#!','MZ','PK\x03\x04')):
            raise ValueError('Executable or archive content rejected')
        quarantine.mkdir(parents=True,exist_ok=True)
        name=uuid4().hex+'.txt'
        (quarantine/name).write_text(text)
        return {'quarantine_file':name,'bytes':len(body),'text':text[:12000]}
    finally: conn.close()

def execute(action, root: Path, runtime: Path, rules):
    t,a=action.tool,action.args
    root.mkdir(parents=True,exist_ok=True)
    if t=='list_files':
        p=root if a.get('path','.')=='.' else safe_path(root,a['path'])
        return {'files':sorted(x.name for x in p.iterdir())[:1000]}
    if t in {'read_file','write_file','delete_file'}:
        p=safe_path(root,a['path'])
        if t=='read_file':
            if p.stat().st_size>100000: raise ValueError('File too large')
            return {'content':p.read_text()}
        if t=='write_file':
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(a['content'])
            return {'written':a['path']}
        p.unlink()
        return {'deleted':a['path']}
    if t=='run_command':
        if not command_allowed(a['command']): raise ValueError('Command not supported')
        name=a['command'].strip()
        binaries={'pwd':'/bin/pwd','ls':'/bin/ls','whoami':'/usr/bin/whoami'}
        done=subprocess.run([binaries[name]],cwd=root,env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=5,check=True)
        return {'stdout':done.stdout[:10000]}
    if t=='fetch_url':
        caps=[r.limit for r in rules if r.type=='download_block']
        return fetch(a['url'],runtime/'quarantine',min(caps or [1000000]))
    if t=='send_message':
        with (runtime/'outbox.jsonl').open('a') as f:
            f.write(json.dumps({'run_id':action.run_id,**a})+'\n')
        return {'sent':True,'simulated':True}
    if t=='spend_money': return {'paid_inr':a['amount_inr'],'payee':a['payee'],'simulated':True}
    raise ValueError('Unknown tool')
