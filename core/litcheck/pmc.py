"""Pinned open-access text from the PMC Cloud Service bucket.

The bucket (https://pmc-oa-opendata.s3.amazonaws.com) is read over plain
anonymous HTTPS: a prefix listing gives the article's versions, the metadata
JSON gives licence, open-access status, retraction flag and the text's md5,
and the `.txt` is accepted only if its bytes match that md5. The OA Web
Service (oa.fcgi) is retired.

Outcomes are a closed set. The licence is recorded, not gated: reading a text
to check a quote is not republishing it. Open-access status is gated: only
text PMC marks as open access is fetched. Retraction is read from the
metadata field and reported, never decided from an exception's wording.
"""
import hashlib
import json
import re

from . import transport as _transport

FETCHED = 'FETCHED'
MD5_MISMATCH = 'MD5_MISMATCH'
NOT_OPEN_ACCESS = 'NOT_OPEN_ACCESS'
MISSING_UPSTREAM = 'MISSING_UPSTREAM'
UNVERIFIABLE = 'UNVERIFIABLE'
OUTCOMES = (FETCHED, MD5_MISMATCH, NOT_OPEN_ACCESS, MISSING_UPSTREAM, UNVERIFIABLE)

BUCKET = 'https://pmc-oa-opendata.s3.amazonaws.com'
PMCID_PATTERN = re.compile(r'^PMC[1-9]\d*$')
MD5_PATTERN = re.compile(r'[?&]md5=([0-9a-f]{32})(?:&|$)')


def _check_pmcid(pmcid):
    if not isinstance(pmcid, str) or not PMCID_PATTERN.match(pmcid):
        raise ValueError('not a PMCID: %r (expected PMC followed by digits)' % (pmcid,))


def list_url(pmcid):
    return _transport.build_url(BUCKET + '/', [('list-type', '2'), ('prefix', pmcid + '.')])


def metadata_url(pmcid, version):
    return '%s/%s.%d/%s.%d.json' % (BUCKET, pmcid, version, pmcid, version)


def text_url(pmcid, version):
    return '%s/%s.%d/%s.%d.txt' % (BUCKET, pmcid, version, pmcid, version)


def _get(url, transport):
    """(status, body, headers) or (None, reason, None) when the call failed."""
    try:
        return transport(url)
    except Exception as exc:
        return None, 'request failed (%s)' % exc, None


def versions(pmcid, transport=None):
    """(outcome, sorted versions). An empty listing is NOT_OPEN_ACCESS."""
    _check_pmcid(pmcid)
    status, body, _ = _get(list_url(pmcid), _transport.get_transport(transport))
    if status is None or status != 200:
        if status == 404:
            return MISSING_UPSTREAM, []
        return UNVERIFIABLE, []
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        return UNVERIFIABLE, []
    if '<ListBucketResult' not in text:
        return UNVERIFIABLE, []
    pattern = re.compile(r'<Key>%s\.(\d+)/' % re.escape(pmcid))
    found = sorted(set(int(v) for v in pattern.findall(text)))
    if not found:
        return NOT_OPEN_ACCESS, []
    return FETCHED, found


def metadata(pmcid, version, transport=None):
    """(outcome, info dict or None) for one version's metadata JSON."""
    _check_pmcid(pmcid)
    status, body, headers = _get(metadata_url(pmcid, version), _transport.get_transport(transport))
    if status == 404:
        return MISSING_UPSTREAM, None
    if status != 200:
        return UNVERIFIABLE, None
    try:
        data = json.loads(body.decode('utf-8'))
        if data.get('pmcid') != pmcid or int(data.get('version')) != version:
            return UNVERIFIABLE, None
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
        return UNVERIFIABLE, None
    match = MD5_PATTERN.search(str(data.get('text_url') or ''))
    info = {
        'pmcid': pmcid,
        'version': version,
        'license_code': str(data.get('license_code') or '') or None,
        'is_pmc_openaccess': data.get('is_pmc_openaccess') is True,
        'is_retracted': data.get('is_retracted') is True,
        'retraction_field_present': isinstance(data.get('is_retracted'), bool),
        'doi': str(data['doi']).lower() if data.get('doi') else None,
        'text_md5': match.group(1) if match else None,
        'text_sha256': None,
        'metadata_url': metadata_url(pmcid, version),
        'metadata_sha256': _transport.sha256(body),
        'metadata_date': _transport.response_date(headers),
    }
    return FETCHED, info


def fetch_text(pmcid, version=None, transport=None):
    """(outcome, info, text_bytes): the md5-verified text, or why there is none.

    `info` carries pmcid, version, license_code, is_retracted, doi, text_md5
    and text_sha256 whenever the metadata could be read, so a caller can
    report licence and retraction even when no text is fetched.
    """
    _check_pmcid(pmcid)
    transport = _transport.get_transport(transport)
    if version is None:
        outcome, found = versions(pmcid, transport)
        if outcome != FETCHED:
            return outcome, None, None
        version = found[-1]
    outcome, info = metadata(pmcid, version, transport)
    if outcome != FETCHED:
        return outcome, info, None
    if not info['is_pmc_openaccess']:
        return NOT_OPEN_ACCESS, info, None
    if not info['text_md5']:
        return UNVERIFIABLE, info, None  # open access, but no md5 to pin the text to
    status, body, _ = _get(text_url(pmcid, version), transport)
    if status == 404:
        return MISSING_UPSTREAM, info, None
    if status != 200:
        return UNVERIFIABLE, info, None
    if hashlib.md5(body).hexdigest() != info['text_md5']:
        return MD5_MISMATCH, info, None
    info['text_sha256'] = _transport.sha256(body)
    return FETCHED, info, body
