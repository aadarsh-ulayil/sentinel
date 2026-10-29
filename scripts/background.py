"""Manage SENTINEL's per-user macOS login services. No administrator access."""
import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime' / 'macos'
AGENTS = Path.home() / 'Library' / 'LaunchAgents'
APP = Path.home() / 'Applications' / 'SENTINEL.app'
STAGED_APP = Path('/private/tmp') / ('sentinel-build-' + str(getattr(os, 'getuid', lambda: 'windows')())) / 'SENTINEL.app'
LABELS = ('local.sentinel.gateway', 'local.sentinel.companion')


def manifests(root=ROOT, app=APP):
    runtime = root / '.runtime' / 'macos'
    common = {'RunAtLoad': True, 'ThrottleInterval': 5, 'WorkingDirectory': str(root)}
    return {
        LABELS[0]: {**common, 'Label': LABELS[0], 'KeepAlive': True,
                    'ProgramArguments': [str(root / '.venv' / 'bin' / 'python'), '-m', 'sentinel'],
                    'StandardOutPath': str(runtime / 'gateway.log'),
                    'StandardErrorPath': str(runtime / 'gateway.log')},
        LABELS[1]: {**common, 'Label': LABELS[1], 'KeepAlive': {'SuccessfulExit': False},
                    'ProgramArguments': [str(app / 'Contents' / 'MacOS' / 'SENTINEL')],
                    'StandardOutPath': str(runtime / 'companion.log'),
                    'StandardErrorPath': str(runtime / 'companion.log')},
    }


def prepare():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    for label, manifest in manifests().items():
        path = RUNTIME / (label + '.plist')
        path.write_bytes(plistlib.dumps(manifest))
        print(path)


def launchctl(*args, check=True):
    return subprocess.run(['/bin/launchctl', *args], check=check, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'install', 'start', 'stop', 'status', 'uninstall'])
    command = parser.parse_args().command
    domain = f'gui/{os.getuid()}'
    if command == 'prepare':
        prepare()
        return
    if command == 'install':
        if not (STAGED_APP / 'Contents' / 'MacOS' / 'SENTINEL').exists():
            raise SystemExit('First run: .venv/bin/python scripts/build_macos.py')
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(STAGED_APP)], check=True)
        APP.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(STAGED_APP, APP, dirs_exist_ok=True)
        prepare()
        AGENTS.mkdir(parents=True, exist_ok=True)
        for label in LABELS:
            launchctl('bootout', domain + '/' + label, check=False)
            target = AGENTS / (label + '.plist')
            shutil.copy2(RUNTIME / target.name, target)
            target.chmod(0o644)
            result = launchctl('bootstrap', domain, str(target), check=False)
            if result.returncode:
                raise SystemExit(result.stderr.strip() or 'launchctl could not load ' + label)
        print('Background protection and notifications installed. They start at login.')
    elif command == 'start':
        for label in LABELS:
            target = AGENTS / (label + '.plist')
            if not target.exists():
                raise SystemExit('Run install first.')
            if launchctl('print', domain + '/' + label, check=False).returncode:
                launchctl('bootstrap', domain, str(target))
            else:
                launchctl('kickstart', domain + '/' + label)
        print('SENTINEL background services started.')
    elif command in ('stop', 'uninstall'):
        for label in reversed(LABELS):
            launchctl('bootout', domain + '/' + label, check=False)
            if command == 'uninstall':
                (AGENTS / (label + '.plist')).unlink(missing_ok=True)
        print('Services stopped.' if command == 'stop' else 'Login services removed; source and audit history preserved.')
    elif command == 'status':
        for label in LABELS:
            result = launchctl('print', domain + '/' + label, check=False)
            if result.returncode:
                print(label + ': not loaded')
            else:
                summary = [line.strip() for line in result.stdout.splitlines()
                           if line.strip().startswith(('state =', 'pid =', 'last exit code ='))]
                print(label + ': ' + ', '.join(summary))


if __name__ == '__main__':
    main()
