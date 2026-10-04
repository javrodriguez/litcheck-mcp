"""Command line, and the two operations the MCP server shares with it.

    litcheck check --id <ID> --quote <TEXT> [--claim <TEXT>] [--log <PATH>] [--json]
    litcheck search {epmc|litsense|pubmed|citing} <QUERY> [--log <PATH>] [--json]
    litcheck verify-log [<PATH>]
    litcheck annotate --seq <N> --support {supports|contradicts|absent} --by <NAME> [--log <PATH>]

Exit status: 0 only for FOUND in a paper whose retraction status is not
RETRACTED (check), SEARCHED (search), an intact chain (verify-log) and a
recorded annotation; 3 for FOUND in a paper whose retraction status is
RETRACTED (check); 1 for every other verdict; 2 for a request that could not
be understood or a damaged log. `check` never raises: a failure, including a bug in litcheck,
becomes UNVERIFIABLE with its reason.
"""
import argparse
import json
import sys

from . import __version__
from . import ids as _ids
from . import paths as _paths
from . import pmc as _pmc
from . import quote as _quote
from . import record as _record
from . import retraction as _retraction
from . import search as _search

FOUND = _quote.FOUND
NOT_FOUND = _quote.NOT_FOUND
TOO_SHORT = _quote.TOO_SHORT
NOT_CHECKABLE = _quote.NOT_CHECKABLE
UNVERIFIABLE = 'UNVERIFIABLE'
VERDICTS = (FOUND, NOT_FOUND, TOO_SHORT, NOT_CHECKABLE, UNVERIFIABLE)

ENGINES = {'epmc': 'europe_pmc', 'litsense': 'litsense', 'pubmed': 'pubmed', 'citing': 'citing'}


class InputError(ValueError):
    """The request itself is unusable; the message says what to change."""


def _resolve(identifier, transport):
    try:
        return _ids.resolve(identifier, transport)
    except ValueError as exc:
        raise InputError(str(exc))


def resolve_identifier(identifier, transport=None):
    """ids.resolve, with unusable input raised as InputError."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise InputError('the identifier is empty; pass a DOI, a PMCID or "PMID <number>"')
    return _resolve(identifier, transport)


def _pmc_block(outcome, info):
    info = info or {}
    return {'outcome': outcome, 'version': info.get('version'),
            'license_code': info.get('license_code'), 'text_sha256': info.get('text_sha256'),
            'text_md5_ok': True if outcome == _pmc.FETCHED else (
                False if outcome == _pmc.MD5_MISMATCH else None),
            'is_pmc_openaccess': info.get('is_pmc_openaccess'),
            'is_retracted': info.get('is_retracted')}


def _pmc_metadata(pmcid, transport):
    """(outcome, info) for the latest version's metadata, no text fetched."""
    outcome, found = _pmc.versions(pmcid, transport)
    if outcome != _pmc.FETCHED:
        return outcome, None
    return _pmc.metadata(pmcid, found[-1], transport)


def _pmc_error(pmcid, outcome, info):
    """Why PMC's retraction flag was not read, when it should have been."""
    if not pmcid or info is not None:
        return None
    if outcome in (_pmc.MISSING_UPSTREAM, _pmc.UNVERIFIABLE):
        return 'the PMC metadata for %s could not be read (%s)' % (pmcid, outcome)
    if outcome == _pmc.NOT_OPEN_ACCESS:
        return ('PMC lists %s but the PMC Cloud Service holds no copy of it, so its '
                'retraction flag could not be read' % pmcid)
    return None


def _guard(resolved, result):
    """A clean negative needs a resolved identifier: if no service could place
    the paper, an empty answer from Crossref says nothing about it."""
    if result['status'] == _retraction.NOT_RETRACTED_AS_OF and resolved['status'] != _ids.RESOLVED:
        result['status'] = _retraction.UNVERIFIABLE
        result['as_of'] = None
        result['reason'] = ('no retraction notice was found, but the identifier did not resolve '
                            '(%s: %s), so PMC could not be consulted and an empty answer says '
                            'nothing' % (resolved['status'], resolved['reason']))
    return result


def retraction_for(identifier, transport=None, clock=None):
    """(resolved, retraction) for an identifier, without fetching any text."""
    resolved = resolve_identifier(identifier, transport)
    info, outcome = None, None
    if resolved['pmcid']:
        outcome, info = _pmc_metadata(resolved['pmcid'], transport)
    doi = resolved['doi'] or (info or {}).get('doi')
    if resolved['status'] == _ids.UNVERIFIABLE and not doi and info is None:
        result = _retraction.status(None, None, transport, clock)
        result['reason'] = 'the identifier could not be resolved: %s' % resolved['reason']
        return resolved, result
    return resolved, _guard(resolved, _retraction.status(
        doi, info, transport, clock, _pmc_error(resolved['pmcid'], outcome, info)))


def run_check(identifier, quote, claim=None, transport=None, log=None, clock=None):
    """Check one quote against one paper's pinned open-access text; never raises
    except InputError for an unusable request. Returns the evidence dict."""
    if not isinstance(quote, str) or not quote.strip():
        raise InputError('the quote is empty; pass the passage exactly as you would cite it')
    resolved = resolve_identifier(identifier, transport)
    evidence = {'verdict': UNVERIFIABLE, 'reason': None, 'claim': claim,
                'identifier': identifier, 'resolved': None, 'pmc': _pmc_block(None, None),
                'retraction': None, 'quote': None, 'log_seq': None}
    try:
        _check(evidence, resolved, quote, transport, clock)
    except Exception as exc:  # a bug in litcheck must still come back as a verdict
        evidence['verdict'] = UNVERIFIABLE
        evidence['reason'] = 'internal error in litcheck (%s: %s); this is a bug' % (
            type(exc).__name__, exc)
    if evidence['quote'] is None:
        evidence['quote'] = dict(_quote.not_checkable(), verdict=evidence['verdict'])
    evidence['quote']['text'] = quote
    if log:
        line = _record.append(log, 'evidence', dict(_record.evidence_payload(
            claim, identifier, _resolved_block(resolved), _log_pmc(evidence['pmc']),
            evidence['retraction'], evidence['quote']), verdict=evidence['verdict'],
            reason=evidence['reason']), clock=clock)
        evidence['log_seq'] = line['seq']
    return evidence


def _resolved_block(resolved):
    return {'pmid': resolved['pmid'], 'pmcid': resolved['pmcid'], 'doi': resolved['doi']}


def _log_pmc(block):
    return dict((k, block[k]) for k in ('outcome', 'version', 'text_sha256', 'text_md5_ok',
                                        'license_code'))


def _check(evidence, resolved, quote_text, transport, clock):
    evidence['resolved'] = dict(resolved)
    outcome, info, body = None, None, None
    if resolved['pmcid']:
        outcome, info, body = _pmc.fetch_text(resolved['pmcid'], None, transport)
        evidence['pmc'] = _pmc_block(outcome, info)
    doi = resolved['doi'] or (info or {}).get('doi')
    evidence['retraction'] = _guard(resolved, _retraction.status(
        doi, info, transport, clock, _pmc_error(resolved['pmcid'], outcome, info)))
    if resolved['status'] == _ids.UNVERIFIABLE:
        evidence['verdict'] = UNVERIFIABLE
        evidence['reason'] = 'the identifier could not be resolved: %s' % resolved['reason']
        return
    if not resolved['pmcid']:
        evidence['verdict'] = NOT_CHECKABLE
        evidence['reason'] = ('no open-access text: the article is not in PubMed Central (%s)'
                              % resolved['reason'])
        return
    if outcome == _pmc.FETCHED:
        try:
            text = body.decode('utf-8')
        except UnicodeDecodeError:
            evidence['reason'] = 'the PMC text is not valid UTF-8'
            return
        evidence['quote'] = _quote.check(quote_text, text)
        evidence['verdict'] = evidence['quote']['verdict']
        if evidence['verdict'] == TOO_SHORT:
            evidence['reason'] = ('the quote is under %d characters; a match that short '
                                  'says little about the passage' % _quote.MIN_QUOTE_CHARS)
        return
    reasons = {
        _pmc.NOT_OPEN_ACCESS: (NOT_CHECKABLE, 'PMC holds no open-access text for %s'),
        _pmc.MISSING_UPSTREAM: (NOT_CHECKABLE, 'the PMC Cloud Service has no copy of %s'),
        _pmc.MD5_MISMATCH: (UNVERIFIABLE, 'the text of %s did not match its pinned md5'),
        _pmc.UNVERIFIABLE: (UNVERIFIABLE,
                            'the PMC Cloud Service could not be read, or gave no md5, for %s'),
    }
    verdict, reason = reasons[outcome]
    evidence['verdict'] = verdict
    evidence['reason'] = reason % resolved['pmcid']


def run_search(engine, query, limit=25, mindate=None, maxdate=None, transport=None, log=None,
               clock=None):
    """One recorded search; returns {status, items, **meta}."""
    try:
        if engine == 'europe_pmc':
            status, items, meta = _search.europe_pmc(query, page_size=limit,
                                                     transport=transport, log=log, clock=clock)
        elif engine == 'litsense':
            status, items, meta = _search.litsense(query, limit=limit, transport=transport,
                                                   log=log, clock=clock)
        elif engine == 'pubmed':
            status, items, meta = _search.pubmed(query, mindate=mindate, maxdate=maxdate,
                                                 retmax=limit, transport=transport, log=log,
                                                 clock=clock)
        elif engine == 'citing':
            status, items, meta = _search.citing(query, per_page=limit, transport=transport,
                                                 log=log, clock=clock)
        else:
            raise InputError('unknown engine %r; use europe_pmc, litsense, pubmed or citing'
                             % (engine,))
    except _search.SearchError as exc:
        raise InputError(str(exc))
    result = dict(meta)
    result.update({'status': status, 'items': items})
    return result


# ---- command line -------------------------------------------------------------------------

def parser():
    top = argparse.ArgumentParser(prog='litcheck', description=(
        'Check quoted passages against pinned open-access PMC texts, check retraction '
        'status, and keep a hash-chained log of every search.'))
    top.add_argument('--version', action='version', version='litcheck ' + __version__)
    sub = top.add_subparsers(dest='command')
    sub.required = True

    check = sub.add_parser('check', help='check a quote against a paper')
    check.add_argument('--id', required=True, help='DOI, PMCID, or "PMID <number>"')
    check.add_argument('--quote', required=True)
    check.add_argument('--claim')
    check.add_argument('--log', help='log file (default: %s)' % _paths.LOG_ENV)
    check.add_argument('--json', action='store_true')

    search = sub.add_parser('search', help='run and record a literature search')
    search.add_argument('engine', choices=sorted(ENGINES))
    search.add_argument('query')
    search.add_argument('--limit', type=int, default=25)
    search.add_argument('--mindate')
    search.add_argument('--maxdate')
    search.add_argument('--log')
    search.add_argument('--json', action='store_true')

    verify = sub.add_parser('verify-log', help='re-walk the hash chain of a log')
    verify.add_argument('path', nargs='?')

    annotate = sub.add_parser('annotate', help="record a person's support verdict")
    annotate.add_argument('--log')
    annotate.add_argument('--seq', type=int, required=True)
    annotate.add_argument('--support', required=True, choices=_record.SUPPORT)
    annotate.add_argument('--by', required=True)
    return top


def _ids_text(resolved):
    return ' · '.join('%s %s' % (k, resolved.get(k) or '-') for k in ('pmid', 'pmcid', 'doi'))


def _retraction_lines(retraction):
    if retraction is None:
        return ['not checked']
    head = retraction['status']
    if retraction.get('as_of'):
        head += ' ' + retraction['as_of']
    if retraction.get('concern'):
        head += ' (expression of concern on record)'
    if retraction.get('reason'):
        head += ': ' + retraction['reason']
    lines = [head]
    for source in retraction['sources']:
        if source['retracted'] is None:
            state = 'no answer'
        else:
            state = 'retracted' if source['retracted'] else 'not retracted'
        when = ' (checked %s)' % source['checked_at'] if source['checked_at'] else ''
        lines.append('%s: %s%s' % (source['source'], state, when))
    return lines


def format_check(evidence, log_label):
    pmc = evidence['pmc']
    quote = evidence['quote']
    rows = [('verdict', [evidence['verdict'] + (': ' + evidence['reason']
                                                if evidence['reason'] else '')]),
            ('identifier', [evidence['identifier']])]
    if evidence['resolved']:
        rows.append(('resolved', [_ids_text(evidence['resolved'])]))
    if pmc['outcome']:
        text = 'version %s · licence %s · %s' % (pmc['version'], pmc['license_code'] or '-',
                                                 pmc['outcome'])
        if pmc['text_sha256']:
            text += ' · md5 ok · sha256 %s' % pmc['text_sha256']
        rows.append(('pmc text', [text]))
    rows.append(('retraction', _retraction_lines(evidence['retraction'])))
    if quote['verdict'] == FOUND:
        where = 'characters %d-%d of the normalised (%s) text' % (
            quote['offsets'][0], quote['offsets'][1], quote['normalisation'])
        if quote['paragraph'] is not None:
            where += ', paragraph %d' % quote['paragraph']
        rows.append(('quote', ['FOUND at ' + where]))
    elif quote['verdict'] == NOT_FOUND:
        rows.append(('quote', ['NOT_FOUND; ignoring case: %s' % (
            'found' if quote['casefold_found'] else 'not found')]))
    else:
        rows.append(('quote', [quote['verdict']]))
    if evidence['log_seq'] is not None:
        rows.append(('log', ['line %d of %s' % (evidence['log_seq'], log_label)]))
    out = []
    for label, values in rows:
        for i, value in enumerate(values):
            out.append('%-11s %s' % (label if i == 0 else '', value))
    return '\n'.join(line.rstrip() for line in out)


def format_search(result, log_label):
    head = '%s %s: %s' % (result['engine'], result['status'],
                          'hit count %s' % result['hit_count'] if result['hit_count'] is not None
                          else (result['reason'] or ''))
    lines = [head]
    if result['reason'] and result['status'] != _search.UNVERIFIABLE:
        lines.append('note: ' + result['reason'])
    for item in result['items']:
        ident = ' '.join('%s %s' % (k, item[k]) for k in ('pmid', 'pmcid', 'doi') if item.get(k))
        label = item.get('title') or item.get('text') or ''
        if len(label) > 100:
            label = label[:97] + '...'
        lines.append('- %s%s: %s' % (ident, (' (%s)' % item['year']) if item.get('year') else '',
                                    label))
    if result['log_seq'] is not None:
        lines.append('log: line %d of %s' % (result['log_seq'], log_label))
    return '\n'.join(lines)


def check_exit_status(evidence):
    """0 for FOUND, 3 for FOUND in a RETRACTED paper, 1 for every other verdict."""
    if evidence['verdict'] != FOUND:
        return 1
    retraction = evidence['retraction'] or {}
    return 3 if retraction.get('status') == _retraction.RETRACTED else 0


def _log_path(value):
    return value or _paths.default_log_path()


def main(argv=None, transport=None, clock=None, out=None, log_label=None):
    out = out or sys.stdout
    args = parser().parse_args(argv)

    def say(text):
        out.write(text + '\n')

    try:
        if args.command == 'check':
            log = _log_path(args.log)
            evidence = run_check(args.id, args.quote, args.claim, transport, log, clock)
            if args.json:
                say(json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False))
            else:
                say(format_check(evidence, log_label or log))
            return check_exit_status(evidence)
        if args.command == 'search':
            log = _log_path(args.log)
            result = run_search(ENGINES[args.engine],
                                args.query, args.limit, args.mindate, args.maxdate, transport,
                                log, clock)
            if args.json:
                say(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
            else:
                say(format_search(result, log_label or log))
            return 0 if result['status'] == _search.SEARCHED else 1
        if args.command == 'verify-log':
            path = _log_path(args.path)
            result = _record.verify(path)
            label = log_label or path
            if result['ok']:
                say('chain intact: %d lines in %s; head sha256 %s'
                    % (result['lines'], label, result['head_sha256'] or '-'))
                return 0
            say('chain broken in %s: %s' % (label, result['reason']))
            return 1
        if args.command == 'annotate':
            log = _log_path(args.log)
            line = _record.annotate(log, args.seq, args.support, args.by, clock=clock)
            say('line %d records: line %d %s (by %s)'
                % (line['seq'], line['target_seq'], line['support'], line['by']))
            return 0
    except (InputError, _record.LogError) as exc:
        sys.stderr.write('litcheck: %s\n' % exc)
        return 2
    return 2
