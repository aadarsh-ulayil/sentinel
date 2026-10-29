"""Run on each target OS: creates a Mac .app or a Windows app folder."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                '--windowed', '--name', 'SENTINEL',
                '--collect-data', 'uvicorn', '--collect-submodules', 'uvicorn',
                '--add-data', str(ROOT / 'sentinel' / 'templates') + ':sentinel/templates',
                '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
                str(ROOT / 'desktop_entry.py')], cwd=ROOT, check=True)
