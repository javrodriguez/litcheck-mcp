"""Default log location per operating system, and the LITCHECK_LOG override."""
import unittest

from litcheck import paths


class PathTests(unittest.TestCase):
    def test_override_wins(self):
        self.assertEqual(paths.default_log_path({'LITCHECK_LOG': '/x/y.jsonl'}, 'linux', '/h'),
                         '/x/y.jsonl')

    def test_windows(self):
        self.assertEqual(paths.default_log_path({'LOCALAPPDATA': 'X:\\profile\\AppData\\Local'},
                                                'win32', 'X:\\profile'),
                         'X:\\profile\\AppData\\Local\\litcheck\\log.jsonl')
        self.assertEqual(paths.default_log_path({}, 'win32', 'X:\\profile'),
                         'X:\\profile\\AppData\\Local\\litcheck\\log.jsonl')

    def test_macos(self):
        self.assertEqual(paths.default_log_path({}, 'darwin', '/h'),
                         '/h/Library/Application Support/litcheck/log.jsonl')

    def test_linux(self):
        self.assertEqual(paths.default_log_path({}, 'linux', '/h'),
                         '/h/.local/share/litcheck/log.jsonl')
        self.assertEqual(paths.default_log_path({'XDG_DATA_HOME': '/data'}, 'linux', '/h'),
                         '/data/litcheck/log.jsonl')
        # the XDG spec says a relative value is invalid and must be ignored
        self.assertEqual(paths.default_log_path({'XDG_DATA_HOME': 'rel'}, 'linux', '/h'),
                         '/h/.local/share/litcheck/log.jsonl')


if __name__ == '__main__':
    unittest.main()
