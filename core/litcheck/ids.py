"""Identifiers: find DOIs, PMIDs and PMCIDs in text, and convert between them.

Conversion uses the PMC ID converter, which "will only return related IDs if
the article is in PubMed Central"; a DOI it cannot map falls back to a Europe
PMC `DOI:"<doi>"` search. The converter rejects a request that mixes id types,
so ids are sent in one request per type.
"""
import json
import re

from . import transport as _transport

RESOLVED = 'RESOLVED'
NOT_FOUND = 'NOT_FOUND'
UNVERIFIABLE = 'UNVERIFIABLE'
VERDICTS = (RESOLVED, NOT_FOUND, UNVERIFIABLE)

KINDS = ('doi', 'pmid', 'pmcid')

IDCONV = 'https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/'
EPMC_SEARCH = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'

DOI_PATTERN = re.compile(r'10\.\d{4,9}/\S+')
PMID_PATTERN = re.compile(r'\bPMID\s*:?\s*(\d{1,9})\b', re.I)
PMCID_PATTERN = re.compile(r'\bPMC\d{1,9}\b', re.I)
DOI_PREFIX = re.compile(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', re.I)
TRAILING = '.,;:\'"'
CLOSERS = {')': '(', ']': '[', '}': '{', '>': '<'}
BATCH = 50


def _trim(value):
    """Drop trailing punctuation a sentence adds; keep balanced brackets."""
    while value:
        last = value[-1]
        if last in TRAILING:
            value = value[:-1]
        elif last in CLOSERS and value.count(last) > value.count(CLOSERS[last]):
            value = value[:-1]
        else:
            break
    return value


def find_identifiers(text):
    """Every (kind, value) in `text`, in order of appearance, without repeats.

    DOIs may be written as URLs; a PMID needs a `PMID` cue; a PMCID is `PMC`
    followed by digits. Values are normalised.
    """
    found = []
    taken = []
    for match in DOI_PATTERN.finditer(text):
        value = _trim(match.group())
        if '/' not in value or value.endswith('/'):
            continue
        found.append((match.start(), 'doi', normalise('doi', value)))
        taken.append((match.start(), match.start() + len(value)))
    for kind, pattern in (('pmid', PMID_PATTERN), ('pmcid', PMCID_PATTERN)):
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in taken):
                continue
            value = match.group(1) if kind == 'pmid' else match.group()
            found.append((match.start(), kind, normalise(kind, value)))
    result = []
    for _, kind, value in sorted(found, key=lambda item: item[0]):
        if (kind, value) not in result:
            result.append((kind, value))
    return result


def normalise(kind, value):
    value = value.strip()
    if kind == 'doi':
        return DOI_PREFIX.sub('', value).lower()
    if kind == 'pmcid':
        return 'PMC' + str(int(value[3:]))
    if kind == 'pmid':
        return str(int(value))
    raise ValueError('unknown identifier kind: %r' % (kind,))


def _empty(kind, value):
    # a DOI that was asked about stays known even when no service maps it, so a
    # retraction check can still ask Crossref about it
    return {'kind': kind, 'requested': value, 'status': UNVERIFIABLE,
            'pmid': None, 'pmcid': None, 'doi': value if kind == 'doi' else None,
            'source': None, 'reason': None}


def idconv_url(kind, values):
    return _transport.build_url(IDCONV, [('ids', ','.join(values)), ('idtype', kind),
                                         ('format', 'json')])


def epmc_doi_url(doi):
    return _transport.build_url(EPMC_SEARCH, [('query', 'DOI:"%s"' % doi),
                                              ('resultType', 'lite'), ('format', 'json'),
                                              ('pageSize', '1')])


def _idconv(kind, values, transport):
    """{requested value: result} for one converter request."""
    url = idconv_url(kind, values)
    results = dict((v, _empty(kind, v)) for v in values)
    try:
        status, body, _ = transport(url)
    except Exception as exc:
        for result in results.values():
            result['reason'] = 'the PMC ID converter could not be reached (%s)' % exc
        return results
    if status != 200:
        for result in results.values():
            result['reason'] = 'the PMC ID converter answered HTTP %s' % status
        return results
    try:
        payload = json.loads(body.decode('utf-8'))
        records = payload['records']
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        for result in results.values():
            result['reason'] = 'the PMC ID converter returned an unreadable response'
        return results
    for record in records:
        if not isinstance(record, dict):
            continue
        requested = str(record.get('requested-id', ''))
        key = normalise(kind, requested) if requested else None
        if key not in results:
            continue
        result = results[key]
        result['source'] = 'pmc-idconv'
        if record.get('status') == 'error' or not record.get('pmcid'):
            result['status'] = NOT_FOUND
            result['reason'] = str(record.get('errmsg') or 'not in PubMed Central')
            continue
        result['status'] = RESOLVED
        result['pmcid'] = normalise('pmcid', str(record['pmcid']))
        result['pmid'] = str(record['pmid']) if record.get('pmid') else None
        result['doi'] = normalise('doi', str(record['doi'])) if record.get('doi') else None
        result['reason'] = None
    for result in results.values():
        if result['source'] is None and result['reason'] is None:
            result['reason'] = 'the PMC ID converter returned no record for it'
    return results


def _epmc_doi(result, transport):
    """Fill a DOI the converter could not map from a Europe PMC DOI search."""
    doi = result['requested']
    previous = result['reason']
    try:
        status, body, _ = transport(epmc_doi_url(doi))
    except Exception as exc:
        result['status'] = UNVERIFIABLE
        result['reason'] = ('%s; the Europe PMC fallback could not be reached (%s)'
                            % (previous, exc))
        return result
    if status != 200:
        result['status'] = UNVERIFIABLE
        result['reason'] = '%s; the Europe PMC fallback answered HTTP %s' % (previous, status)
        return result
    try:
        payload = json.loads(body.decode('utf-8'))
        hits = payload['resultList']['result']
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        result['status'] = UNVERIFIABLE
        result['reason'] = '%s; the Europe PMC fallback returned an unreadable response' % previous
        return result
    hits = [h for h in hits if isinstance(h, dict)
            and normalise('doi', str(h.get('doi') or '')) == doi]
    if not hits:
        result['status'] = NOT_FOUND
        result['source'] = 'europe-pmc'
        result['reason'] = 'neither PubMed Central nor Europe PMC knows this DOI'
        return result
    hit = hits[0]
    result['status'] = RESOLVED
    result['source'] = 'europe-pmc'
    result['doi'] = doi
    result['pmid'] = str(hit['pmid']) if hit.get('pmid') else None
    result['pmcid'] = normalise('pmcid', str(hit['pmcid'])) if hit.get('pmcid') else None
    result['reason'] = None if result['pmcid'] else 'known to Europe PMC, not in PubMed Central'
    return result


def convert(ids, transport=None):
    """Resolve [(kind, value), ...] to dicts with pmid, pmcid, doi and a status.

    status is RESOLVED, NOT_FOUND or UNVERIFIABLE; `reason` says why when it
    is not RESOLVED (or when a resolved article has no PMCID).
    """
    transport = _transport.get_transport(transport)
    ids = [(kind, normalise(kind, value)) for kind, value in ids]
    results = {}
    for kind in KINDS:
        values = []
        for k, v in ids:
            if k == kind and v not in values:
                values.append(v)
        for start in range(0, len(values), BATCH):
            for value, result in _idconv(kind, values[start:start + BATCH], transport).items():
                results[(kind, value)] = result
    for (kind, _), result in sorted(results.items()):
        if kind == 'doi' and result['status'] == NOT_FOUND:
            _epmc_doi(result, transport)
    return [results[(kind, value)] for kind, value in ids]


def resolve(identifier, transport=None):
    """One identifier string (as a person writes it) to a convert() result.

    Raises ValueError when the string holds no identifier or more than one.
    """
    found = find_identifiers(identifier)
    if not found:
        raise ValueError(
            'no DOI, PMID or PMCID found in %r; write a DOI (10.xxxx/...), a PMCID '
            '(PMC123456) or a PMID with its cue (PMID 123456)' % (identifier,))
    if len(found) > 1:
        raise ValueError(
            'found %d identifiers in %r (%s); pass exactly one'
            % (len(found), identifier, ', '.join('%s %s' % kv for kv in found)))
    return convert(found, transport)[0]
