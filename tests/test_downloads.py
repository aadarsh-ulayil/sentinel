import pytest
from sentinel import tools

class Response:
    status=200
    headers={'Content-Type':'text/plain'}
    body=b'hello'
    def getheader(self,name,default=None): return self.headers.get(name,default)
    def read(self,limit): return self.body[:limit]

@pytest.fixture
def connection(monkeypatch):
    response=Response()
    monkeypatch.setattr(tools.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('93.184.216.34',443))])
    class Connection:
        def __init__(self,host,address): assert host=='example.com'; assert address=='93.184.216.34'
        def request(self,*a,**kw): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(tools,'PinnedHTTPS',Connection)
    return response

def test_text_quarantine(tmp_path,connection):
    result=tools.fetch('https://example.com',tmp_path,100)
    assert (tmp_path/result['quarantine_file']).read_text()=='hello'

@pytest.mark.parametrize('field,value',[
 ('status',302),('headers',{'Content-Type':'application/zip'}),
 ('headers',{'Content-Type':'text/plain','Content-Encoding':'gzip'}),
 ('body',b'#!/bin/sh\necho bad'),('body',b'PK\x03\x04archive'),('body',b'x'*101),
])
def test_response_guards(tmp_path,connection,field,value):
    setattr(connection,field,value)
    with pytest.raises(ValueError): tools.fetch('https://example.com',tmp_path,100)
    assert not list(tmp_path.iterdir())

def test_private_dns(tmp_path,monkeypatch):
    monkeypatch.setattr(tools.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='network destinations'): tools.fetch('https://example.com',tmp_path,100)
