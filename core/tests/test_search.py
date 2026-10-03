"""Searches: parsed from recorded responses, and every call recorded in the log."""
import json
import os
import shutil
import tempfile
import unittest

from litcheck import record, search, transport
from tests import FIXTURES, pinned_clock, replay

LITSENSE_QUERY = 'arteriosclerosis functional depletion of large-artery elasticity'
PUBMED_TERM = 'ELSA-Brasil coronary artery calcium'


def fixture_sha(name):
    with open(os.path.join(FIXTURES, name + '.meta.json')) as handle:
        return json.load(handle)['body_sha256']


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.log = os.path.join(self.dir, 'log.jsonl')

    def test_litsense_sentences(self):
        status, items, meta = search.litsense(LITSENSE_QUERY, transport=replay(), log=self.log,
                                              clock=pinned_clock())
        self.assertEqual(status, search.SEARCHED)
        self.assertEqual(meta['hit_count'], 100)
        self.assertEqual(len(items), 100)
        first = items[0]
        self.assertEqual((first['source'], first['pmid'], first['pmcid']),
                         ('litsense', '24511534', 'PMC3910517'))
        self.assertIsNone(first['title'])  # LitSense carries no title or DOI
        self.assertIsNone(first['doi'])
        self.assertTrue(first['text'].startswith('On the other hand large artery elasticity'))
        self.assertEqual(meta['response_sha256'],
                         fixture_sha('litsense-sentences-large-artery-elasticity'))
        [line] = record.read(self.log)
        self.assertEqual((line['kind'], line['engine'], line['query'], line['hit_count']),
                         ('search', 'litsense', LITSENSE_QUERY, 100))
        self.assertEqual(line['params'], {'query': LITSENSE_QUERY, 'rerank': 'true'})
        self.assertEqual(line['returned_ids'][0], 'PMC3910517')
        self.assertEqual(meta['log_seq'], 1)

    def test_litsense_limit_trims_items_not_hit_count(self):
        status, items, meta = search.litsense(LITSENSE_QUERY, limit=3, transport=replay())
        self.assertEqual((len(items), meta['hit_count'], meta['log_seq']), (3, 100, None))

    def test_pubmed_with_esummary(self):
        status, items, meta = search.pubmed(PUBMED_TERM, mindate='2015', maxdate='2017', retmax=5,
                                            transport=replay(), log=self.log)
        self.assertEqual(status, search.SEARCHED)
        self.assertEqual(meta['hit_count'], 10)
        self.assertEqual([i['pmid'] for i in items],
                         ['28647689', '28302272', '27901176', '27488360', '27236256'])
        self.assertEqual((items[0]['pmcid'], items[0]['doi'], items[0]['year']),
                         ('PMC5669156', '10.1161/jaha.116.005088', '2017'))
        self.assertTrue(items[0]['title'].startswith('Associations of Cigarette Smoking'))
        self.assertIsNone(items[1]['pmcid'])
        [line] = record.read(self.log)
        self.assertEqual(line['params']['datetype'], 'pdat')
        self.assertNotIn('email', line['params'])
        self.assertNotIn('tool', line['params'])

    def test_every_returned_item_gets_a_logged_id(self):
        self.assertEqual(search._ids([{'doi': '10.1/x'}, {'openalex_id': 'W1'},
                                      {'epmc_id': 'AGR:1'}, {}]),
                         ['10.1/x', 'W1', 'AGR:1', '(no id)'])

    def test_pubmed_needs_both_dates(self):
        with self.assertRaises(search.SearchError):
            search.pubmed(PUBMED_TERM, mindate='2015', transport=replay())

    def test_empty_query_is_refused(self):
        for fn in (search.europe_pmc, search.litsense, search.pubmed, search.citing):
            with self.assertRaises(search.SearchError):
                fn('  ', transport=replay())

    def test_failed_searches_are_unverifiable_and_still_logged(self):
        def broken(url):
            raise OSError('network down')
        calls = ((search.europe_pmc, 'arteriosclerosis'), (search.litsense, 'arteriosclerosis'),
                 (search.pubmed, 'arteriosclerosis'), (search.citing, 'W2741809807'),
                 (search.citing, '10.1371/journal.pcbi.1003285'))
        for transport_ in (broken, lambda url: (503, b'', {}), lambda url: (200, b'<html>', {})):
            for fn, query in calls:
                status, items, meta = fn(query, transport=transport_, log=self.log)
                self.assertEqual((status, items), (search.UNVERIFIABLE, []), fn.__name__)
                self.assertTrue(meta['reason'], fn.__name__)
        rows = record.read(self.log)
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(r['status'] == search.UNVERIFIABLE for r in rows))
        self.assertTrue(record.verify(self.log)['ok'])

    def test_europe_pmc_503_reason_mentions_the_sort_gotcha(self):
        _, _, meta = search.europe_pmc('x', transport=lambda url: (503, b'', {}))
        self.assertIn('invalid sort field', meta['reason'])

    def test_request_urls(self):
        seen = []

        def capture(url):
            seen.append(url)
            raise OSError('stop')
        search.europe_pmc('a b', page_size=5000, sort_by_date=True, transport=capture)
        search.citing('W123', per_page=500, transport=capture)
        search.citing('https://doi.org/10.1371/Journal.X', transport=capture)
        self.assertEqual(seen[0], 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
                                  '?query=a%20b&resultType=lite&format=json&pageSize=1000'
                                  '&sort=FIRST_PDATE_D%20desc')
        self.assertEqual(seen[1], 'https://api.openalex.org/works?filter=cites:W123&per_page=100')
        self.assertEqual(seen[2], 'https://api.openalex.org/works/doi:10.1371/journal.x')
        for url in seen:
            self.assertEqual(url, transport.strip_contact(url))

    def test_europe_pmc_recorded(self):
        status, items, meta = search.europe_pmc('arteriosclerosis large-artery elasticity',
                                                transport=replay())
        self.assertEqual(status, search.SEARCHED)
        self.assertGreater(meta['hit_count'], 0)

    def test_citing_recorded(self):
        # W2474002222 is the worked example's paper (doi:10.1590/1516-3180.2016.1344090516)
        status, items, meta = search.citing('W2474002222', transport=replay())
        self.assertEqual(status, search.SEARCHED)
        self.assertGreater(len(items), 0)


if __name__ == '__main__':
    unittest.main()
