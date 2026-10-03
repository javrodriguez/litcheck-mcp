"""Where the log lives by default, per operating system.

    Windows  %LOCALAPPDATA%\\litcheck\\log.jsonl
    macOS    ~/Library/Application Support/litcheck/log.jsonl
    Linux    $XDG_DATA_HOME/litcheck/log.jsonl, else ~/.local/share/litcheck/log.jsonl

LITCHECK_LOG, when set, overrides all of these.
"""
import ntpath
import os
import sys

LOG_ENV = 'LITCHECK_LOG'
APP = 'litcheck'
FILENAME = 'log.jsonl'


def default_log_path(environ=None, platform=None, home=None):
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    override = environ.get(LOG_ENV, '').strip()
    if override:
        return override
    home = home or os.path.expanduser('~')
    if platform.startswith('win'):
        base = environ.get('LOCALAPPDATA') or ntpath.join(home, 'AppData', 'Local')
        return ntpath.join(base, APP, FILENAME)
    if platform == 'darwin':
        return os.path.join(home, 'Library', 'Application Support', APP, FILENAME)
    base = environ.get('XDG_DATA_HOME', '').strip()
    if not base or not os.path.isabs(base):
        base = os.path.join(home, '.local', 'share')
    return os.path.join(base, APP, FILENAME)
