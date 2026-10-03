"""PMC Cloud Service: versions, metadata, md5-verified text, closed outcomes."""
import hashlib
import unittest

from litcheck import pmc
from tests import (ABSENT_PMCID, NOT_OA_PMCID, PAPER_DOI, PAPER_PMCID, RETRACTED_PMCID,
                   replay)


class OutcomeTests(unittest.TestCase):
    def test_fetched_open_access_text(self):
        outcome, info, body = pmc.fetch_text(PAPER_PMCID, transport=replay())
        self.assertEqual(outcome, pmc.FETCHED)
        self.assertEqual(info['version'], 1)
        self.assertEqual(info['license_code'], 'CC BY')
        self.assertFalse(info['is_retracted'])
        self.assertEqual(info['doi'], PAPER_DOI)
        self.assertEqual(hashlib.md5(body).hexdigest(), info['text_md5'])
        self.assertEqual(hashlib.sha256(body).hexdigest(), info['text_sha256'])
        self.assertIn(b'Arteriosclerosis consists of functional depletion', body)

    def test_versions(self):
        self.assertEqual(pmc.versions(PAPER_PMCID, replay()), (pmc.FETCHED, [1]))

    def test_md5_mismatch_is_refused(self):
        r = replay()

        def tampered(url):
            status, body, headers = r(url)
            if url.endswith('.txt'):
                body = body.replace(b'large-artery', b'small-artery')
            return status, body, headers
        outcome, info, body = pmc.fetch_text(PAPER_PMCID, transport=tampered)
        self.assertEqual(outcome, pmc.MD5_MISMATCH)
        self.assertIsNone(body)
        self.assertIsNone(info['text_sha256'])

    def test_not_open_access_manuscript(self):
        # an author manuscript: in the bucket, licence TDM, is_pmc_openaccess false
        outcome, info, body = pmc.fetch_text(NOT_OA_PMCID, transport=replay())
        self.assertEqual(outcome, pmc.NOT_OPEN_ACCESS)
        self.assertEqual(info['license_code'], 'TDM')
        self.assertFalse(info['is_pmc_openaccess'])
        self.assertIsNone(body)

    def test_absent_from_the_bucket(self):
        outcome, info, body = pmc.fetch_text(ABSENT_PMCID, transport=replay())
        self.assertEqual((outcome, info, body), (pmc.NOT_OPEN_ACCESS, None, None))

    def test_retraction_read_from_the_metadata_field(self):
        outcome, info = pmc.metadata(RETRACTED_PMCID, 1, replay())
        self.assertEqual(outcome, pmc.FETCHED)
        self.assertTrue(info['is_retracted'])
        self.assertTrue(info['retraction_field_present'])
        self.assertEqual(info['license_code'], 'CC BY')  # recorded, not gated
        self.assertEqual(info['metadata_date'], '2026-10-03T21:32:27Z')

    def test_404_on_metadata_is_missing_upstream(self):
        self.assertEqual(pmc.metadata(PAPER_PMCID, 2, replay()), (pmc.MISSING_UPSTREAM, None))
        self.assertEqual(pmc.fetch_text(PAPER_PMCID, 2, replay())[0], pmc.MISSING_UPSTREAM)

    def test_404_on_listing_is_missing_upstream(self):
        self.assertEqual(pmc.versions(PAPER_PMCID, lambda url: (404, b'', {})),
                         (pmc.MISSING_UPSTREAM, []))

    def test_404_on_text_is_missing_upstream(self):
        r = replay()

        def no_text(url):
            return (404, b'', {}) if url.endswith('.txt') else r(url)
        self.assertEqual(pmc.fetch_text(PAPER_PMCID, transport=no_text)[0], pmc.MISSING_UPSTREAM)

    def test_failures_are_unverifiable(self):
        def broken(url):
            raise OSError('network down')
        for transport in (broken, lambda url: (503, b'', {}), lambda url: (200, b'junk', {})):
            self.assertEqual(pmc.fetch_text(PAPER_PMCID, transport=transport)[0],
                             pmc.UNVERIFIABLE)
        r = replay()

        def bad_meta(url):
            if url.endswith('.json'):
                return 200, b'{"pmcid": "PMC1", "version": 1}', {}
            return r(url)
        self.assertEqual(pmc.fetch_text(PAPER_PMCID, transport=bad_meta)[0], pmc.UNVERIFIABLE)

    def test_rejects_malformed_pmcid(self):
        for bad in ('12345', 'PMC', 'PMC12a', 'pmc123', 'PMC0'):
            with self.assertRaises(ValueError):
                pmc.fetch_text(bad, transport=replay())


if __name__ == '__main__':
    unittest.main()
