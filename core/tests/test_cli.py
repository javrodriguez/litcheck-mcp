"""The command line: verdicts, exit codes, the sample log, and an opt-in live smoke."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from litcheck import cli, quote, record
from tests import (CHANGED_QUOTE, FIXTURE_DAY, FIXTURES, NETWORK, NOT_OA_PMCID, PAPER_PMCID,
                   REPO, RETRACTED_PMCID, TRUE_QUOTE, pinned_clock, replay)

SAMPLE_LOG = os.path.join(FIXTURES, 'sample.log')


def run(argv, transport=None):
    out = io.StringIO()
    code = cli.main(argv, transport=transport or replay(), clock=pinned_clock(), out=out,
                    log_label='<LOG>')
    return code, out.getvalue()


def build_sample_log(path):
    """The committed sample.log, re-derived from the recorded fixtures."""
    steps = (
        ['check', '--id', PAPER_PMCID, '--quote', TRUE_QUOTE, '--claim',
         'Arteriosclerosis is a loss of large-artery elasticity.'],
        ['check', '--id', PAPER_PMCID, '--quote', CHANGED_QUOTE],
        ['search', 'litsense', 'arteriosclerosis functional depletion of large-artery elasticity'],
        ['annotate', '--seq', '1', '--support', 'supports', '--by', 'example reviewer'],
    )
    for argv in steps:
        run(argv + ['--log', path])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.log = os.path.join(self.dir, 'log.jsonl')

    def test_found_exits_zero(self):
        code, out = run(['check', '--id', PAPER_PMCID, '--quote', TRUE_QUOTE, '--log', self.log])
        self.assertEqual(code, 0)
        self.assertIn('verdict     FOUND', out)
        self.assertIn('licence CC BY', out)
        self.assertIn('line 1 of <LOG>', out)

    def test_changed_word_exits_one(self):
        code, out = run(['check', '--id', 'PMID 27355798', '--quote', CHANGED_QUOTE,
                         '--log', self.log])
        self.assertEqual(code, 1)
        self.assertIn('verdict     NOT_FOUND', out)

    def test_json_output_is_the_evidence(self):
        code, out = run(['check', '--id', PAPER_PMCID, '--quote', TRUE_QUOTE, '--log', self.log,
                         '--json'])
        evidence = json.loads(out)
        self.assertEqual(evidence['verdict'], 'FOUND')
        self.assertEqual(evidence['quote']['text'], TRUE_QUOTE)
        self.assertEqual(evidence['pmc']['license_code'], 'CC BY')
        self.assertEqual(evidence['log_seq'], 1)
        [line] = record.read(self.log)
        self.assertEqual(line['quote']['offsets'], evidence['quote']['offsets'])
        self.assertEqual(line['ts'], FIXTURE_DAY)

    def test_not_open_access_is_not_checkable(self):
        code, out = run(['check', '--id', NOT_OA_PMCID, '--quote', TRUE_QUOTE, '--log', self.log])
        self.assertEqual(code, 1)
        self.assertIn('NOT_CHECKABLE', out)

    def test_retracted_paper_is_reported(self):
        code, out = run(['check', '--id', RETRACTED_PMCID, '--quote', TRUE_QUOTE,
                         '--log', self.log, '--json'])
        evidence = json.loads(out)
        self.assertEqual(evidence['retraction']['status'], 'RETRACTED')
        # its text was never recorded, so the quote itself cannot be checked here
        self.assertEqual(evidence['verdict'], 'UNVERIFIABLE')
        self.assertEqual(code, 1)

    def test_unreadable_pmc_bucket_is_never_not_retracted(self):
        r = replay()

        def bucket_down(url):
            if 'pmc-oa-opendata' in url:
                return 503, b'', {}
            return r(url)
        _, result = cli.retraction_for(PAPER_PMCID, bucket_down)
        self.assertEqual(result['status'], 'UNVERIFIABLE')
        pmc_source = [s for s in result['sources'] if s['source'] == 'pmc'][0]
        self.assertIsNone(pmc_source['retracted'])
        self.assertIn('could not be read', pmc_source['error'])

    def test_a_doi_nobody_maps_is_still_asked_of_crossref(self):
        asked = []

        def transport(url):
            asked.append(url)
            return 503, b'', {}
        resolved, result = cli.retraction_for('10.1234/abc', transport)
        self.assertEqual(resolved['doi'], '10.1234/abc')
        self.assertTrue(any('api.crossref.org' in u and '10.1234/abc' in u for u in asked))
        self.assertEqual([s['source'] for s in result['sources']], ['crossref'])

    def test_no_clean_negative_without_a_resolved_identifier(self):
        crossref_empty = b'{"status": "ok", "message": {"items": []}}'

        def unknown_doi(url):
            if 'api.crossref.org' in url:
                return 200, crossref_empty, {}
            if 'idconv' in url:
                return 503, b'', {}
            return 200, b'{"hitCount": 0, "resultList": {"result": []}}', {}
        _, result = cli.retraction_for('10.9999/does.not.exist', unknown_doi)
        self.assertEqual(result['status'], 'UNVERIFIABLE')
        self.assertIn('did not resolve', result['reason'])

    def test_pmc_listed_paper_without_a_cloud_copy_is_never_not_retracted(self):
        r = replay()
        crossref_empty = b'{"status": "ok", "message": {"items": []}}'

        def transport(url):
            if 'api.crossref.org' in url:
                return 200, crossref_empty, {}
            if 'pmc-oa-opendata' in url:
                return r('https://pmc-oa-opendata.s3.amazonaws.com/?list-type=2&prefix=PMC13632646.')
            return r(url)
        _, result = cli.retraction_for(PAPER_PMCID, transport)
        self.assertEqual(result['status'], 'UNVERIFIABLE')
        self.assertIn('holds no copy', result['reason'])

    def test_damaged_log_is_an_input_error_not_a_crash(self):
        with open(self.log, 'wb') as handle:
            handle.write(b'not json\n')
        code, out = run(['search', 'pubmed', 'x', '--log', self.log])
        self.assertEqual(code, 2)

    def test_unusable_identifier_exits_two(self):
        code, out = run(['check', '--id', 'twenty-seven', '--quote', TRUE_QUOTE, '--log', self.log])
        self.assertEqual((code, out), (2, ''))
        self.assertFalse(os.path.exists(self.log))

    def test_a_bug_becomes_unverifiable_not_a_crash(self):
        original = quote.check

        def boom(*args):
            raise RuntimeError('simulated defect')
        quote.check = boom
        try:
            code, out = run(['check', '--id', PAPER_PMCID, '--quote', TRUE_QUOTE,
                             '--log', self.log])
        finally:
            quote.check = original
        self.assertEqual(code, 1)
        self.assertIn('UNVERIFIABLE: internal error in litcheck', out)
        self.assertIn('simulated defect', out)
        self.assertEqual(record.read(self.log)[0]['verdict'], 'UNVERIFIABLE')


class OtherCommandTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.log = os.path.join(self.dir, 'log.jsonl')

    def test_search_and_exit_codes(self):
        code, out = run(['search', 'litsense', 'arteriosclerosis functional depletion of '
                         'large-artery elasticity', '--limit', '2', '--log', self.log])
        self.assertEqual(code, 0)
        self.assertIn('litsense SEARCHED: hit count 100', out)
        code, out = run(['search', 'epmc', 'not recorded', '--log', self.log])
        self.assertEqual(code, 1)
        self.assertIn('UNVERIFIABLE', out)
        code, out = run(['search', 'pubmed', 'x', '--mindate', '2015', '--log', self.log])
        self.assertEqual(code, 2)
        self.assertEqual(len(record.read(self.log)), 2)

    def test_annotate_and_verify(self):
        build_sample_log(self.log)
        self.assertEqual(run(['verify-log', self.log])[0], 0)
        code, out = run(['annotate', '--log', self.log, '--seq', '3', '--support', 'absent',
                         '--by', 'someone'])
        self.assertEqual(code, 2)  # line 3 is a search, not evidence
        with open(self.log, 'rb') as handle:
            data = handle.read()
        with open(self.log, 'wb') as handle:
            handle.write(data.replace(b'large-artery', b'small-artery', 1))
        code, out = run(['verify-log', self.log])
        self.assertEqual(code, 1)
        self.assertIn('chain broken', out)

    def test_sample_log_is_re_derived_from_the_fixtures(self):
        build_sample_log(self.log)
        with open(self.log, 'rb') as built, open(SAMPLE_LOG, 'rb') as committed:
            self.assertEqual(built.read(), committed.read(),
                             'sample.log differs from what the fixtures produce; rebuild it with '
                             'python3 -c "from tests.test_cli import build_sample_log; '
                             'build_sample_log(\'core/tests/fixtures/sample.log\')" (from core/)')

    def test_wrapper_script_verifies_the_sample_log(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.Popen(['sh', os.path.join(REPO, 'litcheck'), 'verify-log', SAMPLE_LOG],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, err)
        self.assertIn(b'chain intact: 4 lines', out)

    def test_module_entry_point(self):
        env = dict(os.environ, PYTHONPATH=os.path.join(REPO, 'core'))
        proc = subprocess.Popen([sys.executable, '-m', 'litcheck', '--version'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b'litcheck 0.1.0', out + err)


@unittest.skipUnless(NETWORK, 'live smoke runs only with LITCHECK_NETWORK_TESTS=1')
class LiveSmoke(unittest.TestCase):
    """Against the real services: found, not found, retracted, one logged search."""

    def test_live_smoke(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        log = os.path.join(directory, 'log.jsonl')
        found = cli.run_check(PAPER_PMCID, TRUE_QUOTE, log=log)
        self.assertEqual(found['verdict'], 'FOUND', found['reason'])
        changed = cli.run_check(PAPER_PMCID, CHANGED_QUOTE, log=log)
        self.assertEqual(changed['verdict'], 'NOT_FOUND', changed['reason'])
        _, retracted = cli.retraction_for(RETRACTED_PMCID)
        self.assertEqual(retracted['status'], 'RETRACTED')
        result = cli.run_search('europe_pmc', 'arteriosclerosis large-artery elasticity', log=log)
        self.assertEqual(result['status'], 'SEARCHED', result['reason'])
        verdict = record.verify(log)
        self.assertTrue(verdict['ok'], verdict['reason'])
        self.assertEqual(verdict['lines'], 3)


if __name__ == '__main__':
    unittest.main()
