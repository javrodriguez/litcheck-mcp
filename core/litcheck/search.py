"""Literature searches, each one recorded.

Four engines: Europe PMC (REST search), NCBI LitSense 2.0 (sentences or
passages), PubMed through E-utilities (esearch, then esummary), and OpenAlex
(works citing a work). Each function returns (status, items, meta):

  status  SEARCHED or UNVERIFIABLE (the search did not complete; an empty
          item list then says nothing about what exists);
  items   dicts with source, pmid, pmcid, doi, title, year (LitSense items
          carry no title or DOI, but add the matching text and its score);
  meta    engine, endpoint, query, params, hit_count, response_sha256,
          reason, log_seq.

Given `log`, every call appends a `search` line to it, failed calls too.
A search can miss papers; a recorded search is a record of what was asked
and what came back, nothing more.
"""
import json

from . import record as _record
from . import transport as _transport

SEARCHED = 'SEARCHED'
UNVERIFIABLE = 'UNVERIFIABLE'
STATUSES = (SEARCHED, UNVERIFIABLE)

EPMC_SEARCH = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
EPMC_DATE_SORT = 'FIRST_PDATE_D desc'
LITSENSE = 'https://www.ncbi.nlm.nih.gov/research/litsense2-api/api/%s/'
LITSENSE_KINDS = ('sentences', 'passages')
EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils'
OPENALEX_WORKS = 'https://api.openalex.org/works'

MAX_EPMC_PAGE = 1000
MAX_OPENALEX_PAGE = 100
MAX_PUBMED = 10000


class SearchError(ValueError):
    """A request that cannot be sent as given; the message says how to fix it."""


def _item(source, pmid=None, pmcid=None, doi=None, title=None, year=None, **extra):
    item = {'source': source, 'pmid': pmid, 'pmcid': pmcid, 'doi': doi, 'title': title,
            'year': year}
    item.update(extra)
    return item


def _str(value):
    if value is None or value == '':
        return None
    return str(value)


def _strip_prefix(value, prefixes):
    value = _str(value)
    if value is None:
        return None
    for prefix in prefixes:
        if value.lower().startswith(prefix):
            return value[len(prefix):].strip('/')
    return value


def _fetch_json(url, transport):
    """(payload, sha256, reason): payload None when the call failed."""
    try:
        status, body, _ = transport(url)
    except Exception as exc:
        return None, None, 'the request failed (%s)' % exc
    digest = _transport.sha256(body)
    if status != 200:
        return None, digest, 'HTTP %s' % status
    try:
        return json.loads(body.decode('utf-8')), digest, None
    except (ValueError, UnicodeDecodeError):
        return None, digest, 'an unreadable response'


def _ids(items):
    """One id per returned item, so the log shows how many came back."""
    out = []
    for item in items:
        out.append(item.get('pmcid') or item.get('pmid') or item.get('doi')
                   or item.get('openalex_id') or item.get('epmc_id') or '(no id)')
    return out


def _finish(engine, endpoint, query, params, status, items, hit_count, digest, reason,
            log, clock):
    meta = {'engine': engine, 'endpoint': endpoint, 'query': query, 'params': params,
            'hit_count': hit_count, 'response_sha256': digest, 'reason': reason,
            'log_seq': None}
    if log:
        line = _record.append(log, 'search', _record.search_payload(
            engine, endpoint, query, params, status, digest, hit_count, _ids(items), reason),
            clock=clock)
        meta['log_seq'] = line['seq']
    return status, items, meta


def _query(query):
    if not isinstance(query, str) or not query.strip():
        raise SearchError('the query is empty; pass the words or the query syntax to search for')
    return query.strip()


def europe_pmc(query, page_size=25, result_type='lite', sort_by_date=False, transport=None,
               log=None, clock=None):
    query = _query(query)
    if result_type not in ('idlist', 'lite', 'core'):
        raise SearchError('result_type must be idlist, lite or core')
    page_size = max(1, min(int(page_size), MAX_EPMC_PAGE))
    params = [('query', query), ('resultType', result_type), ('format', 'json'),
              ('pageSize', str(page_size))]
    if sort_by_date:
        params.append(('sort', EPMC_DATE_SORT))
    payload, digest, reason = _fetch_json(_transport.build_url(EPMC_SEARCH, params),
                                          _transport.get_transport(transport))
    items, hits, status = [], None, UNVERIFIABLE
    if payload is not None:
        try:
            hits = int(payload['hitCount'])
            for r in payload['resultList']['result']:
                items.append(_item('europe_pmc', pmid=_str(r.get('pmid')),
                                   pmcid=_str(r.get('pmcid')),
                                   doi=_str(r.get('doi')) and r['doi'].lower(),
                                   title=_str(r.get('title')), year=_str(r.get('pubYear')),
                                   epmc_id='%s:%s' % (r.get('source'), r.get('id'))))
            status = SEARCHED
        except (KeyError, TypeError, ValueError, AttributeError):
            items, hits, reason = [], None, 'an unexpected response shape'
    if reason and status == UNVERIFIABLE:
        reason = 'Europe PMC search did not complete: %s' % reason
        if '503' in reason:
            reason += ' (Europe PMC also answers 503 to an invalid sort field)'
    return _finish('europe_pmc', EPMC_SEARCH, query, dict(params), status, items, hits, digest,
                   reason, log, clock)


def litsense(query, kind='sentences', rerank=True, limit=None, transport=None, log=None,
             clock=None):
    query = _query(query)
    if kind not in LITSENSE_KINDS:
        raise SearchError('LitSense kind must be sentences or passages')
    endpoint = LITSENSE % kind
    params = [('query', query), ('rerank', 'true' if rerank else 'false')]
    payload, digest, reason = _fetch_json(_transport.build_url(endpoint, params),
                                          _transport.get_transport(transport))
    items, hits, status = [], None, UNVERIFIABLE
    if payload is not None:
        try:
            if not isinstance(payload, list):
                raise TypeError('not a list')
            hits = len(payload)
            for r in payload:
                pmcid = _str(r.get('pmcid'))
                items.append(_item('litsense', pmid=_str(r.get('pmid')), pmcid=pmcid,
                                   text=_str((r.get('text') or '').strip()),
                                   section=_str(r.get('section')),
                                   score=r.get('score')))
            status = SEARCHED
        except (KeyError, TypeError, ValueError, AttributeError):
            items, hits, reason = [], None, 'an unexpected response shape'
    if limit is not None:
        items = items[:max(0, int(limit))]
    if reason and status == UNVERIFIABLE:
        reason = 'LitSense search did not complete: %s' % reason
    return _finish('litsense', endpoint, query, dict(params), status, items, hits, digest,
                   reason, log, clock)


def esummary_url(pmids):
    return _transport.build_url(EUTILS + '/esummary.fcgi',
                                [('db', 'pubmed'), ('id', ','.join(pmids)), ('retmode', 'json')])


def esummary(pmids, transport=None):
    """(items, sha256, reason) for PubMed ids, in the order given."""
    if not pmids:
        return [], None, None
    payload, digest, reason = _fetch_json(esummary_url(pmids), _transport.get_transport(transport))
    if payload is None:
        return None, digest, 'esummary: %s' % reason
    items = []
    try:
        result = payload['result']
        for pmid in pmids:
            entry = result.get(pmid) or {}
            ids = dict((a.get('idtype'), a.get('value')) for a in entry.get('articleids') or [])
            pubdate = _str(entry.get('pubdate'))
            items.append(_item('pubmed', pmid=pmid, pmcid=_str(ids.get('pmc')),
                               doi=_str(ids.get('doi')) and ids['doi'].lower(),
                               title=_str(entry.get('title')),
                               year=pubdate[:4] if pubdate and pubdate[:4].isdigit() else None))
    except (KeyError, TypeError, AttributeError):
        return None, digest, 'esummary: an unexpected response shape'
    return items, digest, None


def pubmed(term, mindate=None, maxdate=None, retmax=50, transport=None, log=None, clock=None):
    term = _query(term)
    if (mindate is None) != (maxdate is None):
        raise SearchError('E-utilities needs both mindate and maxdate (YYYY, YYYY/MM or '
                          'YYYY/MM/DD), or neither')
    retmax = max(1, min(int(retmax), MAX_PUBMED))
    params = [('db', 'pubmed'), ('term', term), ('retmax', str(retmax)), ('retmode', 'json')]
    if mindate is not None:
        params += [('datetype', 'pdat'), ('mindate', str(mindate)), ('maxdate', str(maxdate))]
    transport = _transport.get_transport(transport)
    endpoint = EUTILS + '/esearch.fcgi'
    payload, digest, reason = _fetch_json(_transport.build_url(endpoint, params), transport)
    items, hits, status = [], None, UNVERIFIABLE
    if payload is not None:
        try:
            found = payload['esearchresult']
            hits = int(found['count'])
            pmids = [str(i) for i in found['idlist']]
            summary, _, reason = esummary(pmids, transport)
            if summary is None:
                items = [_item('pubmed', pmid=p) for p in pmids]
                reason = 'titles missing: %s' % reason
            else:
                items = summary
            status = SEARCHED
        except (KeyError, TypeError, ValueError):
            items, hits, reason = [], None, 'an unexpected response shape'
    if reason and status == UNVERIFIABLE:
        reason = 'PubMed search did not complete: %s' % reason
    return _finish('pubmed', endpoint, term, dict(params), status, items, hits, digest, reason,
                   log, clock)


def _openalex_id(value):
    """(W-id, None) or (None, lookup URL) for a DOI given instead."""
    value = value.strip()
    short = _strip_prefix(value, ('https://openalex.org/',))
    if short and short[:1] in 'Ww' and short[1:].isdigit():
        return 'W' + short[1:], None
    doi = _strip_prefix(value, ('https://doi.org/', 'http://doi.org/', 'doi:'))
    if doi and doi.startswith('10.'):
        return None, OPENALEX_WORKS + '/doi:' + doi.lower()
    raise SearchError('citing() takes an OpenAlex work id (W123...) or a DOI, not %r' % value)


def citing(openalex_id_or_doi, per_page=25, transport=None, log=None, clock=None):
    query = _query(openalex_id_or_doi)
    transport = _transport.get_transport(transport)
    work_id, lookup = _openalex_id(query)
    per_page = max(1, min(int(per_page), MAX_OPENALEX_PAGE))
    items, hits, status, digest, reason = [], None, UNVERIFIABLE, None, None
    params = None
    if lookup:
        payload, digest, reason = _fetch_json(lookup, transport)
        if isinstance(payload, dict):
            work_id = _strip_prefix(payload.get('id'), ('https://openalex.org/',))
            if not work_id:
                reason = 'OpenAlex returned no work id for the DOI'
        elif payload is not None:
            reason = 'an unexpected response shape for the DOI lookup'
    if work_id:
        params = [('filter', 'cites:' + work_id), ('per_page', str(per_page))]
        payload, digest, reason = _fetch_json(_transport.build_url(OPENALEX_WORKS, params),
                                              transport)
        if payload is not None:
            try:
                hits = int(payload['meta']['count'])
                for r in payload['results']:
                    ids = r.get('ids') or {}
                    items.append(_item(
                        'openalex',
                        pmid=_strip_prefix(ids.get('pmid'), ('https://pubmed.ncbi.nlm.nih.gov/',)),
                        pmcid=_strip_prefix(ids.get('pmcid'), (
                            'https://www.ncbi.nlm.nih.gov/pmc/articles/',
                            'https://pmc.ncbi.nlm.nih.gov/articles/')),
                        doi=_strip_prefix(r.get('doi'), ('https://doi.org/',)),
                        title=_str(r.get('display_name') or r.get('title')),
                        year=_str(r.get('publication_year')),
                        openalex_id=_strip_prefix(r.get('id'), ('https://openalex.org/',))))
                status = SEARCHED
            except (KeyError, TypeError, ValueError, AttributeError):
                items, hits, reason = [], None, 'an unexpected response shape'
    if reason and status == UNVERIFIABLE:
        reason = 'OpenAlex citing search did not complete: %s' % reason
    for item in items:
        if item['doi']:
            item['doi'] = item['doi'].lower()
    return _finish('openalex_citing', OPENALEX_WORKS, query, dict(params or []), status, items,
                   hits, digest, reason, log, clock)
