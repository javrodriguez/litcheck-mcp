"""Retraction status: PMC's flag and Crossref notices, failing closed."""
import unittest

from litcheck import pmc, retraction
from tests import (FIXTURE_DAY, PAPER_DOI, PAPER_PMCID, RETRACTED_PMCID, pinned_clock,
                   replay)

RETRACTED_DOI = '10.1371/journal.pone.0340378'


def unreachable(url):
    raise OSError('network down')


def info(pmcid):
    outcome, data = pmc.metadata(pmcid, 1, replay())
    assert outcome == pmc.FETCHED
    return data


class StatusTests(unittest.TestCase):
    def test_pmc_flag_alone_is_enough_to_say_retracted(self):
        # Crossref cannot answer here; PMC's flag still decides
        result = retraction.status(RETRACTED_DOI, info(RETRACTED_PMCID), unreachable)
        self.assertEqual(result['status'], retraction.RETRACTED)
        sources = dict((s['source'], s) for s in result['sources'])
        self.assertTrue(sources['pmc']['retracted'])
        self.assertEqual(sources['pmc']['checked_at'], '2026-10-03T21:32:27Z')
        self.assertEqual(len(sources['pmc']['response_sha256']), 64)

    def test_not_retracted_needs_every_source_to_answer(self):
        result = retraction.status(PAPER_DOI, info(PAPER_PMCID), unreachable)
        self.assertEqual(result['status'], retraction.UNVERIFIABLE)
        self.assertIn('Crossref could not be reached', result['reason'])
        self.assertIsNone(result['as_of'])

    def test_recorded_not_retracted_from_both_sources(self):
        result = retraction.status(PAPER_DOI, info(PAPER_PMCID), replay())
        self.assertEqual(result['status'], retraction.NOT_RETRACTED_AS_OF)
        self.assertEqual(result['as_of'], FIXTURE_DAY[:10])
        self.assertEqual([s['source'] for s in result['sources']], ['pmc', 'crossref'])
        self.assertIsNone(result['sources'][1]['error'])
        self.assertFalse(result['sources'][1]['retracted'])

    def test_pmc_only_gives_a_dated_answer_from_the_recorded_response(self):
        result = retraction.status(None, info(PAPER_PMCID), replay())
        self.assertEqual(result['status'], retraction.NOT_RETRACTED_AS_OF)
        self.assertEqual(result['as_of'], FIXTURE_DAY[:10])
        self.assertEqual([s['source'] for s in result['sources']], ['pmc'])

    def test_clock_pins_checked_at(self):
        result = retraction.status(None, info(PAPER_PMCID), replay(),
                                   clock=pinned_clock('2030-01-01T00:00:00Z'))
        self.assertEqual(result['sources'][0]['checked_at'], '2030-01-01T00:00:00Z')
        self.assertEqual(result['as_of'], '2030-01-01')

    def test_failures_are_unverifiable_never_not_retracted(self):
        def broken(url):
            raise OSError('network down')
        for transport in (broken, lambda url: (503, b'', {}), lambda url: (404, b'', {}),
                          lambda url: (200, b'not json', {}),
                          lambda url: (200, b'{"status": "failed"}', {})):
            result = retraction.status(PAPER_DOI, None, transport)
            self.assertEqual(result['status'], retraction.UNVERIFIABLE)
            self.assertTrue(result['reason'])

    def test_a_failed_call_claims_no_check_time(self):
        def broken(url):
            raise OSError('network down')
        result = retraction.status(PAPER_DOI, None, broken)
        self.assertIsNone(result['sources'][0]['checked_at'])

    def test_nothing_to_check(self):
        result = retraction.status(None, None, replay())
        self.assertEqual(result['status'], retraction.UNVERIFIABLE)

    def test_missing_field_is_not_read_as_not_retracted(self):
        data = dict(info(PAPER_PMCID), retraction_field_present=False)
        result = retraction.status(None, data, replay())
        self.assertEqual(result['status'], retraction.UNVERIFIABLE)

    def test_unread_pmc_metadata_blocks_not_retracted(self):
        # a Crossref leg that answers cannot make up for a PMC leg that never did
        result = retraction.status(PAPER_DOI, None, lambda url: (503, b'', {}),
                                   pmc_error='the PMC metadata could not be read')
        self.assertEqual(result['status'], retraction.UNVERIFIABLE)
        self.assertEqual([s['source'] for s in result['sources']], ['pmc', 'crossref'])
        self.assertIn('PMC metadata could not be read', result['reason'])

    def test_notice_types(self):
        for kind in ('retraction', 'withdrawal', 'removal', 'Retraction'):
            self.assertEqual(retraction.notice_effect(kind), 'retracted')
        self.assertEqual(retraction.notice_effect('expression_of_concern'), 'concern')
        for kind in ('correction', 'erratum', 'addendum', 'new_version', '', None):
            self.assertIsNone(retraction.notice_effect(kind))

    def test_updates_url(self):
        self.assertEqual(retraction.crossref_updates_url('10.1016/s0140-6736(97)11096-0'),
                         'https://api.crossref.org/v1/works?filter=updates:10.1016/s0140-6736%2897%2911096-0')

    def test_recorded_crossref_notice(self):
        source = retraction.crossref_source(RETRACTED_DOI, replay())
        self.assertIsNone(source['error'])
        self.assertTrue(source['retracted'])


if __name__ == '__main__':
    unittest.main()
