"""Transport: the replay contract, contact handling, throttle and retries."""
import email.message
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error

from litcheck import transport
from tests import FIXTURES, replay


class FakeResponse(object):
    def __init__(self, status, body, headers=None):
        self.status, self.body = status, body
        self.headers = email.message.Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def getcode(self):
        return self.status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def scripted(answers, seen):
    """An opener that plays back statuses (or exceptions) in order."""
    def opener(request, timeout=None):
        seen.append(request)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, 'x',
                                         email.message.Message(), io.BytesIO(body))
        return FakeResponse(status, body, {'Date': 'Sat, 03 Oct 2026 21:32:25 GMT'})
    return opener


class NoThrottle(object):
    def wait(self, host):
        pass


class ReplayTests(unittest.TestCase):
    def test_serves_recorded_body_and_headers(self):
        r = replay()
        url = 'https://pmc-oa-opendata.s3.amazonaws.com/PMC10496602.1/PMC10496602.1.json'
        status, body, headers = r(url)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode('utf-8'))['license_code'], 'CC BY')
        self.assertEqual(headers['date'], 'Sat, 03 Oct 2026 21:32:25 GMT')

    def test_refuses_unrecorded_url(self):
        with self.assertRaises(LookupError):
            replay()('https://pmc-oa-opendata.s3.amazonaws.com/PMC1.1/PMC1.1.json')

    def test_contact_parameters_are_not_part_of_the_key(self):
        url = 'https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?ids=PMC10496602&idtype=pmcid&format=json'
        status, _, _ = replay()(url + '&tool=litcheck&email=someone%40example.org')
        self.assertEqual(status, 200)

    def test_refuses_hash_mismatch(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        for name in ('pmc-meta-pmc10496602.1.body', 'pmc-meta-pmc10496602.1.meta.json'):
            shutil.copy(os.path.join(FIXTURES, name), tmp)
        with open(os.path.join(tmp, 'pmc-meta-pmc10496602.1.body'), 'ab') as handle:
            handle.write(b' ')
        r = transport.ReplayTransport(tmp)
        with self.assertRaises(ValueError):
            r('https://pmc-oa-opendata.s3.amazonaws.com/PMC10496602.1/PMC10496602.1.json')

    def test_every_fixture_is_well_formed(self):
        names = [n for n in os.listdir(FIXTURES) if n.endswith('.meta.json')]
        self.assertGreaterEqual(len(names), 10)
        for name in names:
            with open(os.path.join(FIXTURES, name)) as handle:
                meta = json.load(handle)
            self.assertEqual(sorted(meta), ['body_sha256', 'date', 'headers', 'provenance',
                                            'status', 'url'], name)
            self.assertTrue(meta['provenance'].startswith('recorded live 20'), name)
            self.assertTrue(meta['provenance'].endswith('by core/tools/record_fixture.py'), name)
            self.assertEqual(meta['url'], transport.strip_contact(meta['url']), name)
            self.assertNotIn('set-cookie', meta['headers'], name)
            with open(os.path.join(FIXTURES, name[:-len('.meta.json')] + '.body'), 'rb') as body:
                data = body.read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), meta['body_sha256'], name)
            self.assertLess(len(data), 2 * 1024 * 1024, name)


class ContactTests(unittest.TestCase):
    def test_strip_contact(self):
        url = 'https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&tool=litcheck&email=a%40example.org&term=a%20b'
        self.assertEqual(transport.strip_contact(url),
                         'https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&term=a%20b')
        self.assertEqual(transport.strip_contact('https://x.org/a/b.json'), 'https://x.org/a/b.json')

    def test_with_contact_per_host(self):
        add = transport.with_contact
        self.assertIn('tool=litcheck', add('https://eutils.ncbi.nlm.nih.gov/x?a=1'))
        self.assertNotIn('email', add('https://eutils.ncbi.nlm.nih.gov/x?a=1'))
        self.assertIn('email=a%40example.org', add('https://eutils.ncbi.nlm.nih.gov/x?a=1', 'a@example.org'))
        self.assertIn('email=a%40example.org', add('https://www.ebi.ac.uk/x?a=1', 'a@example.org'))
        self.assertIn('mailto=a%40example.org', add('https://api.crossref.org/v1/works?a=1', 'a@example.org'))
        self.assertIn('mailto=a%40example.org', add('https://api.openalex.org/works?a=1', 'a@example.org'))
        self.assertEqual(add('https://pmc-oa-opendata.s3.amazonaws.com/a.json', 'a@example.org'),
                         'https://pmc-oa-opendata.s3.amazonaws.com/a.json')

    def test_round_trip_is_stable(self):
        url = transport.build_url('https://www.ebi.ac.uk/x', [('query', 'DOI:"10.1/a(b)"'), ('n', '1')])
        self.assertEqual(transport.strip_contact(transport.with_contact(url, 'a@example.org')), url)

    def test_contact_only_at_send_time(self):
        seen = []
        old = os.environ.get(transport.CONTACT_ENV)
        os.environ[transport.CONTACT_ENV] = 'someone@example.org'
        try:
            transport.live_transport('https://api.crossref.org/v1/works?filter=x',
                                     throttle=NoThrottle(), opener=scripted([(200, b'{}')], seen))
        finally:
            if old is None:
                del os.environ[transport.CONTACT_ENV]
            else:
                os.environ[transport.CONTACT_ENV] = old
        request = seen[0]
        self.assertIn('mailto=someone%40example.org', request.full_url)
        self.assertIn('mailto:someone@example.org', request.get_header('User-agent'))

    def test_user_agent_names_the_project(self):
        self.assertIn('litcheck', transport.user_agent())
        self.assertNotIn('mailto', transport.user_agent())


class RetryTests(unittest.TestCase):
    def call(self, answers):
        seen, sleeps = [], []
        result = transport.live_transport('https://www.ebi.ac.uk/x', throttle=NoThrottle(),
                                          sleep=sleeps.append, opener=scripted(answers, seen))
        return result, len(seen), sleeps

    def test_ok_first_time(self):
        (status, body, headers), calls, sleeps = self.call([(200, b'ok')])
        self.assertEqual((status, body, calls, sleeps), (200, b'ok', 1, []))
        self.assertEqual(headers['date'], 'Sat, 03 Oct 2026 21:32:25 GMT')

    def test_retries_429_and_5xx_at_most_twice(self):
        for status in (429, 500, 502, 503, 504):
            (got, _, _), calls, sleeps = self.call([(status, b''), (status, b''), (status, b'')])
            self.assertEqual((got, calls, len(sleeps)), (status, 3, 2))

    def test_recovers_after_one_retry(self):
        (got, body, _), calls, _ = self.call([(503, b''), (200, b'ok')])
        self.assertEqual((got, body, calls), (200, b'ok', 2))

    def test_never_retries_other_4xx(self):
        for status in (400, 403, 404, 410):
            (got, _, _), calls, sleeps = self.call([(status, b'no')])
            self.assertEqual((got, calls, sleeps), (status, 1, []))

    def test_network_failure_raises_after_retries(self):
        with self.assertRaises(OSError):
            self.call([OSError('down'), OSError('down'), OSError('down')])


class ThrottleTests(unittest.TestCase):
    def test_spaces_requests_per_host(self):
        now, sleeps = [100.0], []

        def sleep(seconds):
            sleeps.append(round(seconds, 2))
            now[0] += seconds
        throttle = transport.Throttle(clock=lambda: now[0], sleep=sleep)
        throttle.wait('www.ncbi.nlm.nih.gov')
        throttle.wait('www.ncbi.nlm.nih.gov')
        throttle.wait('eutils.ncbi.nlm.nih.gov')
        throttle.wait('eutils.ncbi.nlm.nih.gov')
        throttle.wait('pmc-oa-opendata.s3.amazonaws.com')
        throttle.wait('pmc-oa-opendata.s3.amazonaws.com')
        self.assertEqual(sleeps, [1.0, 0.34])

    def test_documented_intervals(self):
        self.assertEqual(transport.HOST_INTERVALS['eutils.ncbi.nlm.nih.gov'], 0.34)
        self.assertEqual(transport.HOST_INTERVALS['www.ncbi.nlm.nih.gov'], 1.0)
        self.assertEqual(transport.HOST_INTERVALS['www.ebi.ac.uk'], 0.2)
        self.assertEqual(transport.HOST_INTERVALS['api.openalex.org'], 0.1)


class DateTests(unittest.TestCase):
    def test_response_date(self):
        self.assertEqual(transport.response_date({'date': 'Sat, 03 Oct 2026 21:32:25 GMT'}),
                         '2026-10-03T21:32:25Z')
        self.assertIsNone(transport.response_date({}))
        self.assertIsNone(transport.response_date({'date': 'not a date'}))

    def test_checked_at_prefers_the_clock(self):
        self.assertEqual(transport.checked_at({'date': 'Sat, 03 Oct 2026 21:32:25 GMT'},
                                              lambda: 'PINNED'), 'PINNED')
        self.assertEqual(transport.checked_at({'date': 'Sat, 03 Oct 2026 21:32:25 GMT'}),
                         '2026-10-03T21:32:25Z')


if __name__ == '__main__':
    unittest.main()
