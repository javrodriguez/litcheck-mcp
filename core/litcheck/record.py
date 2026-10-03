"""The log: append-only JSON lines, each chained to the one before it.

Every line carries `seq` (1, 2, ...), `ts` (UTC ISO 8601), `kind` (evidence,
search or annotate), `prev_sha256` (the sha256 of the previous line's bytes,
newline excluded; 64 zeros for the first line), its payload, and `sha256`
(of the line's own canonical JSON without that field), so an edit to any
line, the last included, is detected when it is accidental or naive. The
hashes are not keyed: a rewrite that recomputes every later hash, or a cut-off
tail, passes `verify`; only a head hash kept elsewhere reveals it.

There is no rewrite function. Annotations record a person's or a named
judge's support verdict about an earlier line; this module never computes one.
"""
import hashlib
import json
import os

from . import transport as _transport

KINDS = ('evidence', 'search', 'annotate')
SUPPORT = ('supports', 'contradicts', 'absent')
ZERO = '0' * 64
RESERVED = ('seq', 'ts', 'kind', 'prev_sha256', 'sha256')

try:
    import fcntl
except ImportError:  # Windows: appends are not locked against a second writer
    fcntl = None


class LogError(ValueError):
    """A request the log cannot honour; the message is written for the caller."""


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _read_lines(path):
    with open(path, 'rb') as handle:
        data = handle.read()
    if not data:
        return []
    if not data.endswith(b'\n'):
        raise LogError('%s does not end with a newline: the last write was cut short' % path)
    return data[:-1].split(b'\n')


def _last(path):
    if not os.path.exists(path):
        return 0, ZERO, []
    lines = _read_lines(path)
    if not lines:
        return 0, ZERO, []
    try:
        last = json.loads(lines[-1].decode('utf-8'))
        seq = int(last['seq'])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise LogError('the last line of %s is not a log line; run verify-log on it' % path)
    return seq, hashlib.sha256(lines[-1]).hexdigest(), lines


def append(path, kind, payload, clock=None):
    """Append one line; return it as a dict (with its seq)."""
    if kind not in KINDS:
        raise LogError('kind must be one of %s, not %r' % (', '.join(KINDS), kind))
    clash = [k for k in RESERVED if k in payload]
    if clash:
        raise LogError('payload may not set %s' % ', '.join(clash))
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, 'ab') as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            seq, prev, lines = _last(path)
            if kind == 'annotate':
                _check_annotation(payload, lines)
            line = dict(payload)
            line.update({'seq': seq + 1, 'ts': clock() if clock else _transport.utc_now(),
                         'kind': kind, 'prev_sha256': prev})
            line['sha256'] = _digest(_canonical(line))
            handle.write((_canonical(line) + '\n').encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return line


def _check_annotation(payload, lines):
    support = payload.get('support')
    if support not in SUPPORT:
        raise LogError('support must be one of %s, not %r' % (', '.join(SUPPORT), support))
    by = payload.get('by')
    if not isinstance(by, str) or not by.strip():
        raise LogError('an annotation needs `by`: the person or named judge giving the verdict')
    target = payload.get('target_seq')
    if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= len(lines):
        raise LogError('target_seq %r is not a line in this log (it has %d lines)'
                       % (target, len(lines)))
    kind = json.loads(lines[target - 1].decode('utf-8')).get('kind')
    if kind != 'evidence':
        raise LogError('line %d is a %s line; annotations attach to evidence lines'
                       % (target, kind))


def evidence_payload(claim, identifier, resolved, pmc, retraction, quote):
    return {'claim': claim, 'identifier': identifier, 'resolved': resolved, 'pmc': pmc,
            'retraction': retraction, 'quote': quote}


def search_payload(engine, endpoint, query, params, status, response_sha256, hit_count,
                   returned_ids, reason=None):
    return {'engine': engine, 'endpoint': endpoint, 'query': query, 'params': params,
            'status': status, 'response_sha256': response_sha256, 'hit_count': hit_count,
            'returned_ids': returned_ids, 'reason': reason}


def annotate(path, target_seq, support, by, clock=None):
    return append(path, 'annotate', {'target_seq': target_seq, 'support': support,
                                     'by': by.strip() if isinstance(by, str) else by},
                  clock=clock)


def verify(path):
    """Re-walk the chain: {ok, lines, first_bad_seq, reason, head_sha256}."""
    result = {'ok': False, 'lines': 0, 'first_bad_seq': None, 'reason': None,
              'head_sha256': None}
    if not os.path.exists(path):
        result['reason'] = 'no log at %s' % path
        return result
    try:
        lines = _read_lines(path)
    except LogError as exc:
        result['reason'] = str(exc)
        return result
    prev = ZERO
    for index, raw in enumerate(lines):
        seq = index + 1
        result['lines'] = seq
        problem = _line_problem(raw, seq, prev)
        if problem:
            result['first_bad_seq'] = seq
            result['reason'] = 'line %d: %s' % (seq, problem)
            return result
        prev = hashlib.sha256(raw).hexdigest()
    result['ok'] = True
    result['head_sha256'] = prev if lines else None
    return result


def _line_problem(raw, seq, prev):
    try:
        line = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return 'not valid JSON'
    if not isinstance(line, dict):
        return 'not a JSON object'
    if line.get('seq') != seq:
        return ('seq is %r, expected %d (a line was removed, added or moved)'
                % (line.get('seq'), seq))
    if line.get('prev_sha256') != prev:
        return 'prev_sha256 does not match the line before it'
    if line.get('kind') not in KINDS:
        return 'unknown kind %r' % (line.get('kind'),)
    if not isinstance(line.get('ts'), str):
        return 'no timestamp'
    claimed = line.pop('sha256', None)
    if claimed != _digest(_canonical(line)):
        return 'its content does not match its own sha256 (the line was edited)'
    if _canonical(dict(line, sha256=claimed)).encode('utf-8') != raw:
        return 'not in canonical form (the line was re-serialised or edited)'
    return None


def read(path):
    """All lines as dicts, in order (no verification; call verify for that)."""
    if not os.path.exists(path):
        return []
    return [json.loads(raw.decode('utf-8')) for raw in _read_lines(path)]
