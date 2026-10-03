"""Identifiers: extraction, normalisation, conversion through recorded responses."""
import unittest

from litcheck import ids
from tests import (NOT_IN_PMC_DOI, PAPER_DOI, PAPER_PMCID, PAPER_PMID, replay)


class FindTests(unittest.TestCase):
    def test_doi_forms(self):
        for text in ('see 10.1590/1516-3180.2016.1344090516.',
                     'https://doi.org/10.1590/1516-3180.2016.1344090516',
                     'doi:10.1590/1516-3180.2016.1344090516;',
                     '(DOI 10.1590/1516-3180.2016.1344090516)'):
            self.assertEqual(ids.find_identifiers(text), [('doi', PAPER_DOI)], text)

    def test_doi_keeps_balanced_brackets(self):
        self.assertEqual(ids.find_identifiers('Lancet 10.1016/S0140-6736(97)11096-0.'),
                         [('doi', NOT_IN_PMC_DOI)])

    def test_pmid_needs_a_cue(self):
        self.assertEqual(ids.find_identifiers('27355798'), [])
        self.assertEqual(ids.find_identifiers('PMID: 27355798'), [('pmid', PAPER_PMID)])
        self.assertEqual(ids.find_identifiers('pmid 27355798'), [('pmid', PAPER_PMID)])

    def test_pmcid(self):
        self.assertEqual(ids.find_identifiers('pmc10496602'), [('pmcid', PAPER_PMCID)])
        self.assertEqual(ids.find_identifiers('XPMC1'), [])

    def test_order_and_repeats(self):
        text = 'PMC10496602, PMID 27355798, again PMC10496602'
        self.assertEqual(ids.find_identifiers(text),
                         [('pmcid', PAPER_PMCID), ('pmid', PAPER_PMID)])

    def test_normalise(self):
        self.assertEqual(ids.normalise('doi', 'https://dx.doi.org/10.1000/ABC'), '10.1000/abc')
        self.assertEqual(ids.normalise('pmcid', 'pmc0012'), 'PMC12')
        self.assertEqual(ids.normalise('pmid', '007'), '7')


class ConvertTests(unittest.TestCase):
    def test_pmcid_and_pmid_resolve(self):
        for kind, value in (('pmcid', PAPER_PMCID), ('pmid', PAPER_PMID)):
            [result] = ids.convert([(kind, value)], replay())
            self.assertEqual(result['status'], ids.RESOLVED)
            self.assertEqual((result['pmid'], result['pmcid'], result['doi']),
                             (PAPER_PMID, PAPER_PMCID, PAPER_DOI))

    def test_one_request_per_type(self):
        r = replay()
        results = ids.convert([('doi', PAPER_DOI), ('doi', NOT_IN_PMC_DOI)], r)
        self.assertEqual(len([u for u in r.requested if 'idconv' in u]), 1)
        self.assertEqual(results[0]['status'], ids.RESOLVED)
        self.assertEqual(results[0]['pmcid'], PAPER_PMCID)
        # not in PMC: the recorded Europe PMC fallback answers for it
        self.assertEqual(r.requested[-1], ids.epmc_doi_url(NOT_IN_PMC_DOI))
        self.assertEqual(results[1]['source'], 'europe-pmc')

    def test_doi_not_in_pmc_falls_back_to_europe_pmc(self):
        [result] = ids.convert([('doi', NOT_IN_PMC_DOI)], replay())
        self.assertEqual(result['source'], 'europe-pmc')
        self.assertEqual(result['status'], ids.RESOLVED)
        self.assertEqual(result['pmid'], '9500320')
        self.assertIsNone(result['pmcid'])

    def test_unreachable_fallback_is_unverifiable_with_both_reasons(self):
        def transport(url):
            if 'idconv' in url:
                return replay()('https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/'
                                '?ids=10.1590/1516-3180.2016.1344090516,10.1016/s0140-6736%2897%2911096-0'
                                '&idtype=doi&format=json')
            raise OSError('network down')
        [result] = ids.convert([('doi', NOT_IN_PMC_DOI)], transport)
        self.assertEqual(result['status'], ids.UNVERIFIABLE)
        self.assertIn('Identifier not found in PMC', result['reason'])
        self.assertIn('Europe PMC fallback could not be reached', result['reason'])

    def test_transient_failures_are_unverifiable(self):
        def broken(url):
            raise OSError('network down')
        for transport in (broken, lambda url: (503, b'', {}), lambda url: (200, b'<html>', {})):
            [result] = ids.convert([('pmcid', PAPER_PMCID)], transport)
            self.assertEqual(result['status'], ids.UNVERIFIABLE)
            self.assertTrue(result['reason'])

    def test_resolve_refuses_none_or_many(self):
        with self.assertRaises(ValueError):
            ids.resolve('no identifier here', replay())
        with self.assertRaises(ValueError):
            ids.resolve('PMC10496602 and 10.1590/1516-3180.2016.1344090516', replay())


if __name__ == '__main__':
    unittest.main()
