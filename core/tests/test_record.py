"""The log: append-only, hash-chained, and loud about any tampering."""
import json
import os
import shutil
import tempfile
import unittest

from litcheck import record
from tests import pinned_clock


def evidence(n):
    return record.evidence_payload(
        'claim %d' % n, 'PMC10496602',
        {'pmid': '27355798', 'pmcid': 'PMC10496602', 'doi': '10.1590/1516-3180.2016.1344090516'},
        {'outcome': 'FETCHED', 'version': 1, 'text_sha256': 'a' * 64, 'text_md5_ok': True,
         'license_code': 'CC BY'},
        {'status': 'UNVERIFIABLE', 'concern': False, 'sources': []},
        {'text': 'a quote long enough %d' % n, 'normalisation': 'q1', 'verdict': 'FOUND',
         'offsets': [1, 2], 'paragraph': 0, 'casefold_found': True})


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, 'nested', 'deeper', 'log.jsonl')

    def build(self, n=4):
        for i in range(n):
            record.append(self.path, 'evidence', evidence(i), clock=pinned_clock())
        return self.path

    def lines(self):
        with open(self.path, 'rb') as handle:
            return handle.read().split(b'\n')[:-1]

    def write(self, lines):
        with open(self.path, 'wb') as handle:
            handle.write(b'\n'.join(lines) + b'\n')

    def test_cold_start(self):
        line = record.append(self.path, 'search', record.search_payload(
            'pubmed', 'https://e', 'q', {'term': 'q'}, 'SEARCHED', 'b' * 64, 0, []))
        self.assertEqual((line['seq'], line['prev_sha256']), (1, '0' * 64))
        self.assertTrue(line['ts'].endswith('Z'))
        result = record.verify(self.path)
        self.assertTrue(result['ok'])
        self.assertEqual(result['lines'], 1)

    def test_chain_and_fields(self):
        self.build(3)
        rows = record.read(self.path)
        self.assertEqual([r['seq'] for r in rows], [1, 2, 3])
        self.assertEqual(rows[0]['ts'], '2026-10-03T21:32:25Z')
        for key in ('claim', 'identifier', 'resolved', 'pmc', 'retraction', 'quote'):
            self.assertIn(key, rows[0])
        verdict = record.verify(self.path)
        self.assertTrue(verdict['ok'])
        self.assertEqual(verdict['lines'], 3)
        self.assertEqual(len(verdict['head_sha256']), 64)

    def test_edit_a_byte_in_the_middle(self):
        self.build()
        lines = self.lines()
        lines[1] = lines[1].replace(b'claim 1', b'claim 7')
        self.write(lines)
        result = record.verify(self.path)
        self.assertFalse(result['ok'])
        self.assertEqual(result['first_bad_seq'], 2)

    def test_edit_a_byte_in_the_last_line(self):
        self.build()
        lines = self.lines()
        lines[-1] = lines[-1].replace(b'claim 3', b'claim 9')
        self.write(lines)
        result = record.verify(self.path)
        self.assertEqual((result['ok'], result['first_bad_seq']), (False, 4))

    def test_drop_a_line(self):
        self.build()
        lines = self.lines()
        del lines[1]
        self.write(lines)
        result = record.verify(self.path)
        self.assertEqual((result['ok'], result['first_bad_seq']), (False, 2))

    def test_swap_lines(self):
        self.build()
        lines = self.lines()
        lines[1], lines[2] = lines[2], lines[1]
        self.write(lines)
        self.assertFalse(record.verify(self.path)['ok'])

    def test_reserialised_line_is_caught(self):
        self.build(2)
        lines = self.lines()
        lines[0] = json.dumps(json.loads(lines[0].decode('utf-8')), indent=1).replace(
            '\n', '').encode('utf-8')
        self.write(lines)
        self.assertEqual(record.verify(self.path)['first_bad_seq'], 1)

    def test_cut_short_write_is_reported(self):
        self.build(2)
        with open(self.path, 'ab') as handle:
            handle.write(b'{"seq": 3')
        result = record.verify(self.path)
        self.assertFalse(result['ok'])
        self.assertIn('newline', result['reason'])

    def test_missing_log(self):
        result = record.verify(os.path.join(self.dir, 'none.jsonl'))
        self.assertFalse(result['ok'])

    def test_annotation_rules(self):
        self.build(2)
        record.append(self.path, 'search', record.search_payload(
            'pubmed', 'https://e', 'q', {}, 'SEARCHED', None, 0, []))
        line = record.annotate(self.path, 1, 'supports', ' A. Reader ')
        self.assertEqual((line['target_seq'], line['support'], line['by']), (1, 'supports', 'A. Reader'))
        for args in ((1, 'proves', 'A. Reader'), (1, 'supports', ''), (99, 'absent', 'A. Reader'),
                     (3, 'absent', 'A. Reader'), (True, 'absent', 'A. Reader')):
            with self.assertRaises(record.LogError):
                record.annotate(self.path, *args)
        self.assertTrue(record.verify(self.path)['ok'])

    def test_payload_cannot_forge_chain_fields(self):
        with self.assertRaises(record.LogError):
            record.append(self.path, 'evidence', {'seq': 9})
        with self.assertRaises(record.LogError):
            record.append(self.path, 'opinion', {})

    def test_no_rewrite_function(self):
        public = [n for n in dir(record) if not n.startswith('_')]
        for name in public:
            for word in ('rewrite', 'delete', 'remove', 'truncate', 'edit', 'update'):
                self.assertNotIn(word, name.lower())


if __name__ == '__main__':
    unittest.main()
