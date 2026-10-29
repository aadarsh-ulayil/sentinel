"""Build the native menu-bar companion without Xcode project files."""
import json
import os
import plistlib
import subprocess
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
APP = Path('/private/tmp') / ('sentinel-build-' + str(os.getuid())) / 'SENTINEL.app'
RUNTIME = ROOT / '.runtime' / 'macos'


def build():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    values = dotenv_values(ROOT / '.env')
    token = values.get('SENTINEL_TOKEN', '')
    if len(token) < 24:
        raise SystemExit('Configure SENTINEL_TOKEN in .env first')
    credentials = RUNTIME / 'credentials.json'
    credentials.write_text(json.dumps({'token': token}))
    credentials.chmod(0o600)
    contents = APP / 'Contents'
    binary_dir = contents / 'MacOS'
    resources = contents / 'Resources'
    binary_dir.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    (resources / 'config.json').write_text(json.dumps({'credentials_file': str(credentials)}))
    info = {'CFBundleIdentifier': 'local.sentinel.companion', 'CFBundleName': 'SENTINEL',
            'CFBundleDisplayName': 'SENTINEL', 'CFBundleExecutable': 'SENTINEL',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '0.1.0',
            'LSUIElement': True, 'LSMinimumSystemVersion': '13.0',
            'NSHumanReadableCopyright': 'SENTINEL hackathon proof of concept'}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-module-cache-path', str(RUNTIME / 'module-cache'),
                    str(ROOT / 'native' / 'Sentinel.swift'), '-o', str(binary_dir / 'SENTINEL'),
                    '-framework', 'WebKit', '-framework', 'Cocoa', '-framework', 'UserNotifications'], check=True)
    for attribute in ('com.apple.FinderInfo', 'com.apple.ResourceFork'):
        subprocess.run(['xattr', '-dr', attribute, str(APP)], capture_output=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(APP)], check=True)
    print(APP)


if __name__ == '__main__':
    build()
