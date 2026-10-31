import time
from fastapi.testclient import TestClient
from sentinel.app import create_app
TOKEN='project-operator-token-long-enough'
AGENT='project-agent-token-long-enough-123'


def wait(c,aid,status):
    for _ in range(200):
        result=c.get(f'/api/actions/{aid}').json()
        if result['status']==status: return result
        time.sleep(.005)
    raise AssertionError(result)


def test_project_access_is_operator_owned_and_edits_require_approval(tmp_path):
    root=tmp_path/'project'; root.mkdir(); (root/'hello.txt').write_text('original')
    with TestClient(create_app(tmp_path/'runtime',TOKEN,agent_token=AGENT)) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        assert c.post('/api/project',json={'root':str(root)},headers={'Authorization':'Bearer '+AGENT}).status_code==403
        c.post('/api/project',json={'root':str(root)})
        def run():return c.post('/api/runs',json={}).json()['id']
        rid=run()
        def submit(tool,args):return c.post('/api/actions',json={'run_id':rid,'tool':tool,'args':args}).json()['action_id']
        wait(c,submit('read_file',{'path':'hello.txt'}),'executed')
        wait(c,submit('write_file',{'path':'hello.txt','content':'no'}),'blocked')
        wait(c,submit('read_file',{'path':'.env'}),'blocked')
        c.post('/api/project',json={'root':str(root),'mode':'approve_changes'})
        wait(c,submit('read_file',{'path':'hello.txt'}),'blocked')
        rid=run()
        aid=submit('write_file',{'path':'hello.txt','content':'approved'})
        wait(c,aid,'waiting_for_human')
        assert (root/'hello.txt').read_text()=='original'
        c.post(f'/api/actions/{aid}/answer',json={'approve':True})
        wait(c,aid,'executed')
        assert (root/'hello.txt').read_text()=='approved'
