"""Optional authoring-time model calls. Never imported by the policy engine."""
import json
import os
from uuid import uuid4
from pydantic import Field
from fastapi import HTTPException
from openai import AsyncOpenAI
from .models import Strict, Rule, Action
from .policy import evaluate

class CompileRequest(Strict):
    english: str = Field(min_length=5,max_length=2000)
class Example(Strict):
    action: Action
    counters: dict[str,int] = Field(default_factory=dict)
    expected: str = Field(pattern='^(allow|block)$')
class Examples(Strict):
    tests: list[Example] = Field(min_length=6,max_length=6)

def readback(r):
    templates={
      'path_allowlist':'File tools must stay inside the run sandbox.',
      'count_limit':f'Delete at most {r.limit} files per run.',
      'cumulative_limit':f'Spend at most {r.limit} rupees per run.',
      'per_call_threshold':f'Pause payments above {r.limit} rupees for human approval.',
      'regex_block':'Block messages with bank-number or OTP patterns.',
      'recipient_allowlist':f'Only message these recipients: {", ".join(r.values)}.',
      'command_rules':'Only pwd, ls, and whoami commands are supported.',
      'domain_allowlist':f'Pause HTTPS requests to domains outside: {", ".join(r.values)}.',
      'download_block':f'Block executables and archives; allow only text downloads up to {r.limit} bytes.',
    }
    return templates[r.type]

def attach_compiler(app,secured,db,runtime,activate,current_rules):
    @app.post('/api/compiler/draft',dependencies=secured)
    async def compile_rule(body:CompileRequest):
        base=os.getenv('META_BASE_URL'); model=os.getenv('META_MODEL'); keyvar=os.getenv('META_API_KEY_ENV')
        key=os.getenv(keyvar or '')
        if not all([base,model,key]): raise HTTPException(503,'Configure META_BASE_URL, META_MODEL, META_API_KEY_ENV and its secret value in .env')
        cid=db.write('INSERT INTO compile_log(english,model,draft_json,tests_json,accepted) VALUES(?,?,?,?,0)',(body.english,model,'null','[]'))
        try:
            async with AsyncOpenAI(base_url=base,api_key=key,timeout=45,max_retries=0) as client:
                first=await client.chat.completions.create(model=model,messages=[{'role':'system','content':'Translate the user rule into exactly one JSON object matching this schema. No markdown, no code. Semantics: '+json.dumps(Rule.model_json_schema())},{'role':'user','content':body.english}])
                rule=Rule.model_validate_json(first.choices[0].message.content or '')
                rule.id='C'+uuid4().hex[:12]
                db.write('UPDATE compile_log SET draft_json=? WHERE id=?',(rule.model_dump_json(),cid))
                second=await client.chat.completions.create(model=model,messages=[{'role':'system','content':'Propose exactly three allow and three block test cases for this deterministic rule. Return JSON matching '+json.dumps(Examples.model_json_schema())+'. Tools: list_files/read_file/write_file/delete_file(path, content for write), spend_money(amount_inr,payee), send_message(recipient,message), run_command(command), fetch_url(url). Counters are deleted and spent. For rules that pause instead of block, do not pretend pause is block: those drafts cannot satisfy this six-test gate.'},{'role':'user','content':rule.model_dump_json()}])
                examples=Examples.model_validate_json(second.choices[0].message.content or '')
            results=[]
            for test in examples.tests:
                verdict=evaluate(test.action,test.counters,[rule],runtime/'compiler-sandbox')
                results.append({**test.model_dump(),'actual':verdict.verdict,'reason':verdict.reason,'passed':verdict.verdict==test.expected})
            eligible=all(t['passed'] for t in results) and sum(t['expected']=='allow' for t in results)==3 and sum(t['expected']=='block' for t in results)==3
            db.write('UPDATE compile_log SET tests_json=? WHERE id=?',(json.dumps(results),cid))
            return {'id':cid,'rule':rule.model_dump(),'readback':readback(rule),'tests':results,'eligible':eligible}
        except Exception as exc:
            # Do not expose upstream messages that may include request or credential details.
            db.write('UPDATE compile_log SET tests_json=? WHERE id=?',(json.dumps({'error':type(exc).__name__}),cid))
            raise HTTPException(422,'Compiler request or validation failed; draft was not activated') from exc
    @app.post('/api/compiler/{cid}/activate',dependencies=secured)
    def activate_draft(cid:int):
        row=db.one('SELECT * FROM compile_log WHERE id=?',(cid,))
        if not row: raise HTTPException(404,'Draft not found')
        tests=json.loads(row['tests_json'])
        if not isinstance(tests,list) or len(tests)!=6 or not all(t.get('passed') for t in tests) or sum(t['expected']=='allow' for t in tests)!=3 or sum(t['expected']=='block' for t in tests)!=3:
            raise HTTPException(409,'Draft must pass three allow and three block tests')
        if row['accepted']: raise HTTPException(409,'Draft already activated')
        rule=Rule.model_validate_json(row['draft_json'])
        activate(current_rules()+[rule],row['english'])
        db.write('UPDATE compile_log SET accepted=1 WHERE id=?',(cid,))
        return {'ok':True,'readback':readback(rule),'scope':'New runs only; base rules remain enforced'}
