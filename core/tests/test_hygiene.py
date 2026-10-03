"""What may never be committed: e-mail addresses and machine-local paths.

Swept over every tracked file and every new file git would add, fixtures
included. A hit prints the path and the rule only, never the matched text,
so the report does not repeat what it found.
"""
import os
import re
import subprocess
import unittest

from tests import REPO

EMAIL = re.compile(br'[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})')
ALLOWED_DOMAINS = (b'noreply.github.com', b'example.org')
HOME_PATHS = re.compile(br'/Use' br'rs/[A-Za-z]|/ho' br'me/[A-Za-z]|'
                        br'[A-Za-z]:\\\\?Use' br'rs\\\\?[A-Za-z]')
SKIP_DIRS = {'.git', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache',
             'dist', 'build'}


def candidate_files():
    """git's view when git is present; otherwise a walk (the 3.6.8 floor image has no git)."""
    try:
        out = subprocess.check_output(
            ['git', '-C', REPO, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
            stderr=subprocess.DEVNULL)
        names = [n.decode('utf-8') for n in out.split(b'\0') if n]
        return [n for n in names if os.path.isfile(os.path.join(REPO, n))]
    except (OSError, subprocess.CalledProcessError):
        found = []
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith('.egg-info')]
            for name in files:
                if not name.endswith('.pyc'):
                    found.append(os.path.relpath(os.path.join(root, name), REPO))
        return found


def allowed(domain):
    domain = domain.lower()
    return any(domain == d or domain.endswith(b'.' + d) for d in ALLOWED_DOMAINS)


def problems(name, data):
    found = []
    if any(not allowed(m.group(1)) for m in EMAIL.finditer(data)):
        found.append('%s: e-mail address outside the allowlist' % name)
    if HOME_PATHS.search(data):
        found.append('%s: home-directory path' % name)
    return found


class HygieneTests(unittest.TestCase):
    def test_files_were_found(self):
        names = candidate_files()
        self.assertGreater(len(names), 20)
        self.assertTrue(any(n.startswith('core/tests/fixtures/') for n in names))

    def test_no_addresses_or_home_paths(self):
        hits = []
        for name in candidate_files():
            with open(os.path.join(REPO, name), 'rb') as handle:
                hits.extend(problems(name, handle.read()))
        self.assertEqual(hits, [], '\n'.join(hits))

    def test_rules_fire(self):
        # samples are assembled at run time so this file holds none of them literally
        at, home, users = b'@', b'/ho' + b'me/', b'/Us' + b'ers/'
        self.assertTrue(problems('x', b'write to someone' + at + b'uni.edu'))
        self.assertTrue(problems('x', b'cd ' + users + b'alice/src'))
        self.assertTrue(problems('x', b'cd ' + home + b'bob'))
        self.assertTrue(problems('x', b'C:\\' + users[1:-1] + b'\\carol'))
        self.assertFalse(problems('x', b'a' + at + b'example.org and 1+x' + at +
                                  b'users.noreply.github.com'))
        self.assertFalse(problems('x', b'see /ABS/PATH/TO/litcheck-mcp and ~/.local/share'))

if __name__ == '__main__':
    unittest.main()
