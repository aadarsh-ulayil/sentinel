import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sentinel.app import create_app

TOKEN='test-token-that-is-long-enough-12345'
@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path,TOKEN,pause_seconds=.15)) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        yield c

def new(c): return c.post('/api/runs',json={}).json()['id']
def submit(c,r,tool,args):
    response=c.post('/api/actions',json={'run_id':r,'tool':tool,'args':args})
    assert response.status_code==202,response.text
    return response.json()['action_id']
def wait(c,aid,terminal=True):
    for _ in range(200):
        a=c.get(f'/api/actions/{aid}').json()
        if a['status'] not in ({'checking','executing','waiting_for_human'} if terminal else {'checking','executing'}): return a
        time.sleep(.005)
    raise AssertionError('Timed out')

def test_auth(client):
    assert client.get('/api/state',headers={'Authorization':''}).status_code==401
    assert client.post('/api/login',json={'token':TOKEN},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/',headers={'Host':'evil.example'}).status_code==400

def test_cumulative_and_failed_execution(client):
    r=new(client)
    for expected in ['executed','executed','blocked']:
        aid=submit(client,r,'spend_money',{'amount_inr':200,'payee':'x'})
        assert wait(client,aid)['status']==expected
    aid=submit(client,r,'delete_file',{'path':'missing'})
    assert wait(client,aid)['status']=='failed'
    assert client.get(f'/api/runs/{r}/report').json()['counters']=={'executed':2,'spent':400}

def test_concurrent_spend(client):
    r=new(client)
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids=list(pool.map(lambda _:submit(client,r,'spend_money',{'amount_inr':200,'payee':'x'}),range(3)))
    assert sorted(wait(client,i)['status'] for i in ids)==['blocked','executed','executed']

def test_delete_limit(client):
    r=new(client)
    for i in range(1,5):
        aid=submit(client,r,'delete_file',{'path':f'draft-{i}.txt'})
        assert wait(client,aid)['status']==('executed' if i<4 else 'blocked')

@pytest.mark.parametrize('approve,expected',[(True,'executed'),(False,'denied')])
def test_human_answer(client,approve,expected):
    r=new(client); aid=submit(client,r,'spend_money',{'amount_inr':300,'payee':'x'})
    assert wait(client,aid,False)['status']=='waiting_for_human'
    assert client.post(f'/api/actions/{aid}/answer',json={'approve':approve}).status_code==200
    assert wait(client,aid)['status']==expected
    assert client.post(f'/api/actions/{aid}/answer',json={'approve':approve}).status_code==409

def test_timeout(client):
    aid=submit(client,new(client),'spend_money',{'amount_inr':300,'payee':'x'})
    a=wait(client,aid); assert a['status']=='denied'; assert a['rule_id']=='TIMEOUT'

def test_kill_reset_report(client):
    r=new(client); aid=submit(client,r,'spend_money',{'amount_inr':300,'payee':'x'})
    wait(client,aid,False)
    assert client.post(f'/api/runs/{r}/kill').status_code==200
    assert wait(client,aid)['status']=='denied'
    assert client.post('/api/actions',json={'run_id':r,'tool':'list_files','args':{}}).status_code==409
    r2=client.post(f'/api/runs/{r}/reset').json()['id']; assert r2!=r
    assert client.get(f'/api/runs/{r}/report').json()['run']['status']=='killed'
    assert client.get(f'/runs/{r}/report').status_code==200

def test_limit(client):
    r=new(client)
    for _ in range(15): wait(client,submit(client,r,'list_files',{}))
    assert client.post('/api/actions',json={'run_id':r,'tool':'list_files','args':{}}).status_code==409
