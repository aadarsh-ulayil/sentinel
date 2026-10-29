"""Pure deterministic decisions: no network, no model, no mutation."""
import re
import shlex
import unicodedata
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit, unquote
from .models import Action, Rule, Verdict

DEFAULT_RULES = [
    Rule(id='R1',type='path_allowlist'), Rule(id='R2',type='count_limit',limit=3),
    Rule(id='R3',type='cumulative_limit',limit=500), Rule(id='R4',type='per_call_threshold',limit=250),
    Rule(id='R5',type='regex_block'), Rule(id='R6',type='recipient_allowlist',values=['alice','bob']),
    Rule(id='R7',type='command_rules'), Rule(id='R8',type='domain_allowlist',values=['example.com']),
    Rule(id='R9',type='download_block',limit=1000000),
]
ARGUMENTS = {'list_files':({'path'},set()), 'read_file':({'path'},{'path'}),
 'write_file':({'path','content'},{'path','content'}),'delete_file':({'path'},{'path'}),
 'run_command':({'command'},{'command'}),'fetch_url':({'url'},{'url'}),
 'send_message':({'recipient','message'},{'recipient','message'}),'spend_money':({'amount_inr','payee'},{'amount_inr','payee'})}
BLOCKED_SUFFIXES = {'.exe','.dmg','.pkg','.sh','.zip','.tar','.gz','.bz2','.xz','.7z','.rar','.msi','.bat','.cmd','.ps1','.app','.jar','.deb','.rpm','.iso','.dll','.so','.dylib'}

def safe_path(root: Path, value: str) -> Path:
    # Reject Windows device names and alternate data streams on every platform.
    windows = PureWindowsPath(value)
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    if windows.drive or ':' in value or '\\' in value or any(
            part.rstrip(' .').split('.')[0].upper() in reserved
            or (part not in {'.', '..'} and part.endswith((' ', '.')))
            for part in windows.parts):
        raise ValueError('Unsupported cross-platform file path')
    root = root.resolve()
    target = (root / value).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError('Path must be a file or folder inside the sandbox')
    return target

def validate_args(a):
    allowed, required = ARGUMENTS[a.tool]
    if set(a.args)-allowed or required-set(a.args):
        raise ValueError('Unexpected or missing tool arguments')
    for key,value in a.args.items():
        if key == 'amount_inr':
            if type(value) is not int or value <= 0: raise ValueError('Amount must be a positive integer in rupees')
        elif not isinstance(value,str) or len(value)>100000: raise ValueError('Arguments must be bounded strings')

def command_allowed(command):
    # No shell, interpreters, flags, or user-selected executables.
    return shlex.split(command) in [['pwd'], ['ls'], ['whoami']]

def evaluate(action: Action, counters: dict, rules: list[Rule], root: Path) -> Verdict:
    results = [Verdict(verdict='allow',rule_id='DEFAULT',reason='All active rules passed')]
    def add(kind, rule, reason): results.append(Verdict(verdict=kind,rule_id=rule.id,reason=reason))
    try:
        validate_args(action)
        for r in rules:
            t, args = action.tool, action.args
            if r.type=='path_allowlist' and t in {'list_files','read_file','write_file','delete_file'}:
                value=args.get('path','.')
                if not (t=='list_files' and value=='.'): safe_path(root,value)
            elif r.type=='count_limit' and t=='delete_file' and counters.get('deleted',0)+1>r.limit:
                add('block',r,'Delete count would exceed the run limit')
            elif r.type=='cumulative_limit' and t=='spend_money' and counters.get('spent',0)+args['amount_inr']>r.limit:
                add('block',r,'Cumulative spending would exceed the run limit')
            elif r.type=='per_call_threshold' and t=='spend_money' and args['amount_inr']>r.limit:
                add('pause',r,'Payment requires human approval')
            elif r.type=='regex_block' and t=='send_message':
                message=unicodedata.normalize('NFKC',args['message'])
                message=''.join(c for c in message if unicodedata.category(c)!='Cf')
                if re.search(r'(?<!\d)(?:\d[\s-]*){9,18}(?!\d)',message) or re.search(r'\b(?:otp|one[ -]?time(?: password| code)?|verification code)\b.{0,30}(?:\d[\s-]*){4,8}',message,re.I):
                    add('block',r,'Message contains a bank-number or OTP pattern')
            elif r.type=='recipient_allowlist' and t=='send_message' and args['recipient'] not in r.values:
                add('block',r,'Recipient is not an approved contact')
            elif r.type=='command_rules' and t=='run_command' and not command_allowed(args['command']):
                add('block',r,'Only pwd, ls, and whoami are supported; arbitrary shell commands are blocked')
            elif r.type in {'domain_allowlist','download_block'} and t=='fetch_url':
                url=urlsplit(args['url'])
                if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in (None,443):
                    add('block',r,'Only HTTPS URLs without credentials on port 443 are supported')
                elif r.type=='domain_allowlist' and url.hostname.lower() not in r.values:
                    add('pause',r,'Domain is not on the allowlist')
                elif r.type=='download_block' and any(s in BLOCKED_SUFFIXES for s in Path(unquote(url.path).lower()).suffixes):
                    add('block',r,'Executable or archive download blocked')
        return max(results,key=lambda x:{'allow':0,'pause':1,'block':2}[x.verdict])
    except Exception as exc:
        return Verdict(verdict='block',rule_id='FAIL_CLOSED',reason=f'Policy rejected action: {exc}')
