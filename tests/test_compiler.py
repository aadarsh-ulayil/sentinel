"""Exercise authoring without network calls or credentials."""
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sentinel.app import create_app
from sentinel import compiler
from sentinel.models import Rule

TOKEN='compiler-operator-token-1234567890'
AGENT='compiler-agent-token-1234567890123'

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('META_BASE_URL','https://example.invalid/v1')
    monkeypatch.setenv('META_MODEL','test-model')
    monkeypatch.setenv('META_API_KEY_ENV','TEST_META_SECRET')
    monkeypatch.setenv('TEST_META_SECRET','not-a-real-secret')
    with TestClient(create_app(tmp_path,TOKEN,agent_token=AGENT)) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        yield c

def mock_model(monkeypatch, replies):
    iterator=iter(replies)
    class Client:
        def __init__(self,**kwargs): self.chat=SimpleNamespace(completions=self)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def create(self,**kwargs):
            content=next(iterator)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))])
    monkeypatch.setattr(compiler,'AsyncOpenAI',Client)

def examples():
    return {'tests':[{'action':{'run_id':'test','tool':'spend_money','args':{'amount_inr':amount,'payee':'demo'}},'counters':{'spent':spent},'expected':expected} for amount,spent,expected in [(100,0,'allow'),(200,100,'allow'),(100,300,'allow'),(401,0,'block'),(200,300,'block'),(1,400,'block')]]}

def test_draft_requires_explicit_activation(client,monkeypatch):
    mock_model(monkeypatch,[{'id':'draft','type':'cumulative_limit','limit':400},examples()])
    before=client.post('/api/runs',json={}).json()
    response=client.post('/api/compiler/draft',json={'english':'Spend at most 400 rupees.'})
    assert response.status_code==200,response.text
    draft=response.json(); assert draft['eligible']; assert '400 rupees' in draft['readback']
    assert client.get('/api/state').json()['rules_version']==before['rules_version']
    assert client.post(f"/api/compiler/{draft['id']}/activate").status_code==200
    after=client.post('/api/runs',json={}).json()
    assert after['rules_version']!=before['rules_version']
    assert client.get(f"/api/runs/{before['id']}/report").json()['run']['rules_version']==before['rules_version']
    assert client.post(f"/api/compiler/{draft['id']}/activate").status_code==409
    rows=client.app.state.store.rows('SELECT rules_json FROM rules WHERE version_hash=?',(after['rules_version'],))
    assert len(json.loads(rows[0]['rules_json']))==10

def test_failed_examples_cannot_activate(client,monkeypatch):
    cases=examples(); cases['tests'][0]['expected']='block'
    mock_model(monkeypatch,[{'id':'draft','type':'cumulative_limit','limit':400},cases])
    draft=client.post('/api/compiler/draft',json={'english':'Spend at most 400 rupees.'}).json()
    assert not draft['eligible']
    assert client.post(f"/api/compiler/{draft['id']}/activate").status_code==409

def test_model_cannot_supply_code(client,monkeypatch):
    mock_model(monkeypatch,[{'id':'evil','type':'execute_python','code':'print(1)'}])
    assert client.post('/api/compiler/draft',json={'english':'Execute Python please'}).status_code==422
    assert client.app.state.store.one('SELECT accepted FROM compile_log')['accepted']==0

def test_missing_credentials(client,monkeypatch):
    monkeypatch.delenv('TEST_META_SECRET')
    assert client.post('/api/compiler/draft',json={'english':'Spend at most 400 rupees.'}).status_code==503

@pytest.mark.parametrize('kind', ['path_allowlist','count_limit','cumulative_limit','per_call_threshold','regex_block','recipient_allowlist','command_rules','domain_allowlist','download_block'])
def test_template_readbacks(kind):
    assert compiler.readback(Rule(id='r',type=kind,limit=100,values=['alice']))
