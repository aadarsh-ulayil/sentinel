"""Human-selected project access. This is a gateway restriction, not an OS sandbox."""
import hashlib
import json
from pathlib import Path
from .models import Verdict

PRIVATE_PARTS = {'.git', '.env', '.ssh', '.aws', '.codex', '.runtime', '.venv', 'node_modules'}


def project_path(root, value):
    from .policy import safe_path
    if value == '.':
        return root
    path = safe_path(root, value)
    relative = path.relative_to(root)
    if any(p.lower() in PRIVATE_PARTS or p.lower().startswith('.env.') or p.lower().endswith(('.pem', '.key')) for p in relative.parts):
        raise ValueError('Private settings, credentials, and internal folders are excluded')
    current = root
    for part in Path(value).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symbolic links are excluded from project access')
    if path.exists() and path.is_file() and path.stat().st_nlink > 1:
        raise ValueError('Files with multiple hard links are excluded')
    return path


def guard(action, project):
    root = Path(project['root'])
    try:
        info = root.stat()
        if not root.is_dir() or [info.st_dev, info.st_ino] != json.loads(project['identity']):
            raise ValueError('The selected folder was moved or replaced; choose it again')
        if action.tool in {'list_files', 'read_file', 'write_file', 'delete_file'}:
            project_path(root, action.args.get('path', '.'))
        if action.tool in {'write_file', 'delete_file'}:
            if project['mode'] == 'read_only':
                raise ValueError('This project is read-only. Change its permissions in SENTINEL to request edits')
            return Verdict(verdict='pause', rule_id='PROJECT_APPROVAL', reason='Changing a real project file requires your approval')
        if action.tool == 'run_command' and action.args.get('command', '').strip() not in {'pwd', 'ls', 'whoami'}:
            raise ValueError('Only bounded inspection commands are available; build scripts are not supported')
    except (ValueError, OSError) as error:
        return Verdict(verdict='block', rule_id='PROJECT_GUARD', reason=str(error))
    return Verdict(verdict='allow', rule_id='PROJECT_ACCESS', reason='Inside the selected project permissions')


def fingerprint(root, value):
    path = project_path(Path(root), value)
    if not path.exists():
        return 'missing'
    if not path.is_file() or path.stat().st_size > 100000:
        raise ValueError('Only regular files up to 100 KB may be changed')
    return hashlib.sha256(path.read_bytes()).hexdigest()
