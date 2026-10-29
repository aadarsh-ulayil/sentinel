"""Keep writable state outside packaged application bundles."""
import os
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
if getattr(sys, 'frozen', False):
    parent = (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
              if sys.platform == 'win32' else Path.home() / 'Library' / 'Application Support')
    DATA = Path(os.environ.get('SENTINEL_HOME', parent / 'SENTINEL'))
else:
    DATA = Path(os.environ.get('SENTINEL_HOME', SOURCE))
