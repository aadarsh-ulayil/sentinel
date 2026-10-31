"""Local assistant setup. Delegate configuration writes to each host's CLI."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import json

TEST_MESSAGE = ('Use only SENTINEL tools for this test. Start a task, list the files in '
                'the allowed folder, wait for the final action result, then finish the task. '
                'Do not use your ordinary terminal, browser, or file tools.')


def find_cli(host):
    if host not in ('codex', 'claude'):
        raise ValueError('Choose Codex or Claude Code.')
    found = shutil.which(host)
    if found:
        return found
    name = host + ('.exe' if sys.platform == 'win32' else '')
    candidates = [Path.home() / '.local/bin' / name,
                  Path('/opt/homebrew/bin') / name, Path('/usr/local/bin') / name]
    if host == 'codex':
        candidates += [Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'),
                       Path('/Applications/Codex.app/Contents/Resources/codex')]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise ValueError(f'{"Codex" if host == "codex" else "Claude Code"} was not found. Install its command-line tool, then reopen this screen.')


def bridge_config(data):
    data = Path(data).resolve()
    python = data / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.is_file():
        raise ValueError('The SENTINEL connection helper is missing. Select the original SENTINEL configuration folder or reinstall the development environment.')
    return {'command': str(python), 'args': ['-m', 'sentinel.mcp_server'],
            'env': {'SENTINEL_HOME': str(data)}}


def existing_config(host):
    if host == 'codex':
        path = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'config.toml'
        if not path.exists():
            return None
        return tomllib.loads(path.read_text()).get('mcp_servers', {}).get('sentinel')
    path = Path(os.environ.get('CLAUDE_CONFIG_DIR', Path.home())) / '.claude.json'
    if not path.exists():
        return None
    return json.loads(path.read_text()).get('mcpServers', {}).get('sentinel')


def connect(host, data):
    cli = find_cli(host)
    config = bridge_config(data)
    try:
        old = existing_config(host)
    except (ValueError, OSError):
        raise ValueError('Could not read the assistant settings. No settings were changed.') from None
    if old:
        actual = old.get('transport', old)
        if all(actual.get(k) == v for k, v in config.items()) and old.get('enabled', True):
            return 'Already configured. Open a new assistant chat and send the test message below.'
        raise ValueError('A different SENTINEL connection already exists. It was left unchanged. Remove that connection in your assistant before connecting here.')
    # Check the helper before changing any host settings. Never print configuration secrets.
    probe = subprocess.run([config['command'], '-c', 'import sentinel.mcp_server'],
                           cwd=str(data), capture_output=True, timeout=20)
    if probe.returncode:
        raise ValueError('The SENTINEL helper could not start. Its MCP dependencies need repair before connecting.')
    args = [cli, 'mcp', 'add']
    if host == 'claude':
        args += ['--scope', 'user']
    args += ['--env', 'SENTINEL_HOME=' + config['env']['SENTINEL_HOME']]
    if host == 'claude':
        args += ['--transport', 'stdio']
    args += ['sentinel', '--', config['command'], *config['args']]
    result = subprocess.run(args, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('The assistant could not save the connection. Check its settings for an existing SENTINEL entry or a permissions restriction, then try again.')
    return 'Connection saved. Restart the assistant, then send the test message below. A saved connection is not yet a verified action.'
