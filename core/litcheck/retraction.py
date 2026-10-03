"""Retraction status from two sources: PMC's own flag and Crossref notices.

Sources:
  pmc       the `is_retracted` field of the PMC Cloud Service metadata;
  crossref  notices that update the DOI (`/v1/works?filter=updates:<doi>`).
            Only update types retraction, withdrawal and removal count as
            retracted; corrections do not; an expression of concern sets
            `concern` and nothing else.

Either source saying retracted gives RETRACTED. NOT_RETRACTED_AS_OF needs
every consulted source to have answered; a source that could not be read
makes the status UNVERIFIABLE (unless another source already says
retracted). `as_of` is the earliest date among the checks, and every check's
`checked_at` comes from the `clock` parameter or, without one, from the
response's own Date header, which under replay is the recorded one.
"""
import json

from . import transport as _transport

RETRACTED = 'RETRACTED'
NOT_RETRACTED_AS_OF = 'NOT_RETRACTED_AS_OF'
UNVERIFIABLE = 'UNVERIFIABLE'
STATUSES = (RETRACTED, NOT_RETRACTED_AS_OF, UNVERIFIABLE)

CROSSREF_WORKS = 'https://api.crossref.org/v1/works'
RETRACTING_TYPES = ('retraction', 'withdrawal', 'removal')
CONCERN_TYPES = ('expression_of_concern',)


def crossref_updates_url(doi):
    return _transport.build_url(CROSSREF_WORKS, [('filter', 'updates:' + doi)])


def notice_effect(update_type):
    """'retracted', 'concern' or None for a Crossref `update-to[].type`."""
    kind = str(update_type or '').strip().lower()
    if kind in RETRACTING_TYPES:
        return 'retracted'
    if kind in CONCERN_TYPES:
        return 'concern'
    return None


def pmc_source(pmc_info, clock=None):
    """A source entry from pmc.metadata()'s info dict."""
    entry = {'source': 'pmc', 'url': pmc_info.get('metadata_url'),
             'checked_at': clock() if clock else (pmc_info.get('metadata_date')
                                                  or _transport.utc_now()),
             'response_sha256': pmc_info.get('metadata_sha256'),
             'retracted': None, 'concern': False, 'notices': [], 'error': None}
    if pmc_info.get('retraction_field_present', True):
        entry['retracted'] = bool(pmc_info.get('is_retracted'))
    else:
        entry['error'] = 'the PMC metadata has no is_retracted field'
    return entry


def crossref_source(doi, transport=None, clock=None):
    url = crossref_updates_url(doi)
    entry = {'source': 'crossref', 'url': url, 'checked_at': None, 'response_sha256': None,
             'retracted': None, 'concern': False, 'notices': [], 'error': None}
    try:
        status, body, headers = _transport.get_transport(transport)(url)
    except Exception as exc:
        # no response, so no check happened; only a pinned clock gives a time
        entry['checked_at'] = clock() if clock else None
        entry['error'] = 'Crossref could not be reached (%s)' % exc
        return entry
    entry['checked_at'] = _transport.checked_at(headers, clock)
    entry['response_sha256'] = _transport.sha256(body)
    if status != 200:
        entry['error'] = 'Crossref answered HTTP %s' % status
        return entry
    try:
        payload = json.loads(body.decode('utf-8'))
        items = payload['message']['items']
        if payload.get('status') != 'ok' or not isinstance(items, list):
            raise ValueError('not an ok item list')
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        entry['error'] = 'Crossref returned an unreadable response'
        return entry
    retracted = False
    for item in items:
        if not isinstance(item, dict):
            continue
        for update in item.get('update-to') or []:
            if not isinstance(update, dict):
                continue
            if str(update.get('DOI', '')).lower() != doi.lower():
                continue
            kind = str(update.get('type', '')).lower()
            entry['notices'].append({'type': kind, 'notice_doi': item.get('DOI'),
                                     'source': update.get('source')})
            effect = notice_effect(kind)
            if effect == 'retracted':
                retracted = True
            elif effect == 'concern':
                entry['concern'] = True
    entry['retracted'] = retracted
    return entry


def status(doi=None, pmc_info=None, transport=None, clock=None):
    """{status, as_of, concern, sources, reason} for a DOI and/or PMC info."""
    sources = []
    if pmc_info is not None:
        sources.append(pmc_source(pmc_info, clock))
    if doi:
        sources.append(crossref_source(doi, transport, clock))
    result = {'status': UNVERIFIABLE, 'as_of': None, 'concern': False,
              'sources': sources, 'reason': None}
    result['concern'] = any(s['concern'] for s in sources)
    if not sources:
        result['reason'] = 'no DOI and no PMC record to check'
        return result
    if any(s['retracted'] for s in sources):
        result['status'] = RETRACTED
        return result
    failed = [s for s in sources if s['retracted'] is None]
    if failed:
        result['reason'] = '; '.join(s['error'] or ('%s did not answer' % s['source'])
                                     for s in failed)
        return result
    result['status'] = NOT_RETRACTED_AS_OF
    result['as_of'] = min(s['checked_at'] for s in sources)[:10]
    return result
