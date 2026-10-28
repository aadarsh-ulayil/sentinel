"""Authoring-time model calls and explicit offline examples; never runtime policy."""
import json
import os
from uuid import uuid4
from pydantic import Field, StrictInt, model_validator
from fastapi import HTTPException
from openai import AsyncOpenAI
from .models import Strict, Rule, Action
from .policy import evaluate, validate_args


class CompileRequest(Strict):
    english: str = Field(min_length=5, max_length=2000)


class Example(Strict):
    action: Action
    counters: dict[str, StrictInt] = Field(default_factory=dict)
    expected: str = Field(pattern='^(allow|block)$')

    @model_validator(mode='after')
    def valid_inputs(self):
        validate_args(self.action)
        if set(self.counters) - {'deleted', 'spent', 'executed'}:
            raise ValueError('Unknown counter')
        if any(value < 0 for value in self.counters.values()):
            raise ValueError('Counters cannot be negative')
        return self


class Examples(Strict):
    tests: list[Example] = Field(min_length=6, max_length=6)


def readback(rule):
    templates = {
        'path_allowlist': 'File tools must stay inside the run sandbox.',
        'count_limit': f'Delete at most {rule.limit} files per run.',
        'cumulative_limit': f'Spend at most {rule.limit} rupees per run.',
        'per_call_threshold': f'Pause payments above {rule.limit} rupees for human approval.',
        'regex_block': 'Block messages with bank-number or OTP patterns.',
        'recipient_allowlist': f'Only message these recipients: {", ".join(rule.values)}.',
        'command_rules': 'Only pwd, ls, and whoami commands are supported.',
        'domain_allowlist': f'Pause HTTPS requests to domains outside: {", ".join(rule.values)}.',
        'download_block': f'Block executables and archives; allow only text downloads up to {rule.limit} bytes.',
    }
    return templates[rule.type]


def assess(examples, rules, root):
    """Test the policy that will actually run, with no tool execution."""
    results = []
    for example in examples.tests:
        verdict = evaluate(example.action, example.counters, rules, root)
        results.append({**example.model_dump(), 'actual': verdict.verdict,
                        'reason': verdict.reason, 'passed': verdict.verdict == example.expected})
    eligible = (all(test['passed'] for test in results)
                and sum(test['expected'] == 'allow' for test in results) == 3
                and sum(test['expected'] == 'block' for test in results) == 3)
    return results, eligible


def pause_probes(rule, root):
    """Fixed boundary checks supplement the six examples for pause-only types."""
    if rule.type == 'per_call_threshold':
        action = Action(run_id='probe', tool='spend_money',
                        args={'amount_inr': rule.limit + 1, 'payee': 'Synthetic vendor'})
    elif rule.type == 'domain_allowlist':
        host = 'sentinel-test.invalid'
        while host in rule.values:
            host = 'other.' + host
        action = Action(run_id='probe', tool='fetch_url', args={'url': 'https://' + host})
    else:
        return []
    verdict = evaluate(action, {}, [rule], root)
    return [{'action': action.model_dump(), 'expected': 'pause', 'actual': verdict.verdict,
             'passed': verdict.verdict == 'pause', 'source': 'fixed deterministic boundary probe'}]


def attach_compiler(app, secured, db, runtime, activate, current_rules):
    root = runtime / 'compiler-sandbox'

    def save_result(cid, rule, examples, source):
        results, eligible = assess(examples, current_rules() + [rule], root)
        probes = pause_probes(rule, root)
        eligible = eligible and all(probe['passed'] for probe in probes)
        db.write('UPDATE compile_log SET draft_json=?,tests_json=? WHERE id=?',
                 (rule.model_dump_json(), json.dumps(results), cid))
        return {'id': cid, 'rule': rule.model_dump(), 'readback': readback(rule),
                'tests': results, 'pause_probes': probes, 'eligible': eligible, 'source': source,
                'scope': 'Adds a rule for new runs. Existing protections remain enforced.'}

    @app.post('/api/compiler/example', dependencies=secured)
    def offline_example():
        """A fixed human-written draft, never a simulated model translation."""
        english = 'Offline example: spend at most 400 rupees in one run.'
        rule = Rule(id='C' + uuid4().hex[:12], type='cumulative_limit', limit=400)
        cases = [(100, 0, 'allow'), (200, 100, 'allow'), (100, 300, 'allow'),
                 (401, 0, 'block'), (200, 300, 'block'), (1, 400, 'block')]
        examples = Examples(tests=[Example(
            action=Action(run_id='offline-example', tool='spend_money',
                          args={'amount_inr': amount, 'payee': 'Synthetic vendor'}),
            counters={'spent': spent}, expected=expected)
            for amount, spent, expected in cases])
        cid = db.write('INSERT INTO compile_log(english,model,draft_json,tests_json,accepted) VALUES(?,?,?,?,0)',
                       (english, 'human-written-offline-example', 'null', '[]'))
        return save_result(cid, rule, examples, 'Offline example — no model was called')

    @app.post('/api/compiler/draft', dependencies=secured)
    async def compile_rule(body: CompileRequest):
        base = os.getenv('META_BASE_URL')
        model = os.getenv('META_MODEL')
        key = os.getenv(os.getenv('META_API_KEY_ENV', ''))
        if not all([base, model, key]):
            raise HTTPException(503, 'Meta API key is not configured. Use the offline example to test review and activation.')
        cid = db.write('INSERT INTO compile_log(english,model,draft_json,tests_json,accepted) VALUES(?,?,?,?,0)',
                       (body.english, model, 'null', '[]'))
        try:
            async with AsyncOpenAI(base_url=base, api_key=key, timeout=45, max_retries=0) as client:
                first = await client.chat.completions.create(model=model, messages=[
                    {'role': 'system', 'content': 'Translate the user rule into exactly one JSON object matching this schema. No markdown, no code. ' + json.dumps(Rule.model_json_schema())},
                    {'role': 'user', 'content': body.english}])
                rule = Rule.model_validate_json(first.choices[0].message.content or '')
                rule.id = 'C' + uuid4().hex[:12]
                db.write('UPDATE compile_log SET draft_json=? WHERE id=?', (rule.model_dump_json(), cid))
                effective = current_rules() + [rule]
                prompt = ('Propose exactly three allow and three block test actions for the COMBINED policy supplied by the user. '
                          'Block beats pause, pause beats allow. Do not label pause as block. The candidate rule is the last rule. '
                          'Use valid tool arguments and realistic nonnegative counters; cover the candidate where possible. '
                          'Tool arguments: list_files(path optional), read_file(path), write_file(path,content), delete_file(path), '
                          'spend_money(amount_inr,payee), send_message(recipient,message), run_command(command), fetch_url(url). '
                          'Command allowlist is pwd/ls/whoami with no arguments. Files stay inside the sandbox. '
                          'Counters are deleted, spent, executed. Only HTTPS is supported. Downloads block executables/archives. '
                          'Return JSON matching: ' + json.dumps(Examples.model_json_schema()))
                second = await client.chat.completions.create(model=model, messages=[
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': json.dumps([item.model_dump() for item in effective])}])
                examples = Examples.model_validate_json(second.choices[0].message.content or '')
            return save_result(cid, rule, examples, 'Meta Model API · ' + model)
        except Exception as exc:
            db.write('UPDATE compile_log SET tests_json=? WHERE id=?',
                     (json.dumps({'error': type(exc).__name__}), cid))
            raise HTTPException(422, 'Compiler request or validation failed; draft was not activated') from exc

    @app.post('/api/compiler/{cid}/activate', dependencies=secured)
    async def activate_draft(cid: int):
        row = db.one('SELECT * FROM compile_log WHERE id=?', (cid,))
        if not row:
            raise HTTPException(404, 'Draft not found')
        if row['accepted']:
            raise HTTPException(409, 'Draft already activated')
        try:
            saved = json.loads(row['tests_json'])
            examples = Examples.model_validate({'tests': [
                {key: test[key] for key in ('action', 'counters', 'expected')} for test in saved]})
            rule = Rule.model_validate_json(row['draft_json'])
        except (ValueError, TypeError, KeyError):
            raise HTTPException(409, 'Draft has no valid six-test set') from None
        rules = current_rules() + [rule]
        results, eligible = assess(examples, rules, root)
        if not eligible or not all(test['passed'] for test in pause_probes(rule, root)):
            raise HTTPException(409, 'Draft must pass three allow and three block tests against the current policy')
        activate(rules, row['english'])
        db.write('UPDATE compile_log SET accepted=1,tests_json=? WHERE id=?', (json.dumps(results), cid))
        return {'ok': True, 'readback': readback(rule), 'scope': 'New runs only; base rules remain enforced'}
