"""HTTP transport: one seam, `transport(url) -> (status, body, headers)`.

Every network call in the core goes through a transport. `live_transport` is
the real one; `ReplayTransport` serves recorded fixtures and refuses anything
it was not given. Modules take `transport=None` and fall back to the live one.

The contact address (LITCHECK_CONTACT) is added only at send time, to the
User-Agent and to the `email`/`mailto` parameters. It is never part of a URL
the core builds, returns or records, and never part of the replay key, so
replay works with no contact set and no address reaches a fixture or a log.
"""
import datetime
import email.utils
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

USER_AGENT = 'litcheck/%s (+https://github.com/javrodriguez/litcheck-mcp)' % __version__
TOOL_NAME = 'litcheck'
CONTACT_ENV = 'LITCHECK_CONTACT'

# Parameters that carry identity, added at send time and stripped from any
# URL that is stored or used as a replay key.
CONTACT_PARAMS = ('email', 'mailto', 'tool')

# Minimum seconds between two requests to the same host.
HOST_INTERVALS = {
    'eutils.ncbi.nlm.nih.gov': 0.34,
    'pmc.ncbi.nlm.nih.gov': 0.34,
    'www.ncbi.nlm.nih.gov': 1.0,  # LitSense: one request per second per user
    'www.ebi.ac.uk': 0.2,
    'api.openalex.org': 0.1,
    'api.crossref.org': 0.1,
}

# Which identity parameters each host takes.
NCBI_PARAM_HOSTS = ('eutils.ncbi.nlm.nih.gov', 'pmc.ncbi.nlm.nih.gov')
EMAIL_PARAM_HOSTS = ('www.ebi.ac.uk',)
MAILTO_PARAM_HOSTS = ('api.crossref.org', 'api.openalex.org')

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 2
BACKOFF_SECONDS = (1.0, 3.0)
MAX_RETRY_AFTER = 10.0


class Throttle(object):
    """Keeps at least HOST_INTERVALS[host] seconds between requests to a host."""

    def __init__(self, intervals=None, clock=None, sleep=None):
        self.intervals = dict(HOST_INTERVALS if intervals is None else intervals)
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.last = {}

    def wait(self, host):
        interval = self.intervals.get(host, 0.0)
        previous = self.last.get(host)
        if previous is not None and interval > 0:
            remaining = interval - (self.clock() - previous)
            if remaining > 0:
                self.sleep(remaining)
        self.last[host] = self.clock()


THROTTLE = Throttle()


def contact():
    value = os.environ.get(CONTACT_ENV, '').strip()
    return value or None


def user_agent(address=None):
    if address:
        return '%s mailto:%s' % (USER_AGENT, address)
    return USER_AGENT


def build_url(base, params):
    """`base?params` with one fixed encoding, so stored and rebuilt URLs agree."""
    if not params:
        return base
    return base + '?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe='/:,')


def strip_contact(url):
    """The URL without email/mailto/tool parameters: the form that is stored."""
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in CONTACT_PARAMS]
    base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    return build_url(base, kept)


def with_contact(url, address=None):
    """The URL as sent: identity parameters added for the hosts that take them."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower()
    extra = []
    if host in NCBI_PARAM_HOSTS:
        extra.append(('tool', TOOL_NAME))
        if address:
            extra.append(('email', address))
    elif host in EMAIL_PARAM_HOSTS and address:
        extra.append(('email', address))
    elif host in MAILTO_PARAM_HOSTS and address:
        extra.append(('mailto', address))
    if not extra:
        return url
    query = parts.query + ('&' if parts.query else '') + urllib.parse.urlencode(extra)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _headers(message):
    return dict((k.lower(), v) for k, v in message.items())


def _retry_delay(attempt, headers):
    delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
    after = (headers or {}).get('retry-after', '')
    if after.strip().isdigit():
        delay = max(delay, min(float(after.strip()), MAX_RETRY_AFTER))
    return delay


def live_transport(url, timeout=20, throttle=None, sleep=None, opener=None):
    """Fetch `url`; return (status, body bytes, lower-cased header dict).

    429 and 5xx are retried at most MAX_RETRIES times with backoff; other 4xx
    are returned at once. A network failure on the last attempt raises OSError,
    which callers turn into UNVERIFIABLE.
    """
    throttle = throttle or THROTTLE
    sleep = sleep or time.sleep
    opener = opener or urllib.request.urlopen
    address = contact()
    request = urllib.request.Request(
        with_contact(url, address), headers={'User-Agent': user_agent(address)})
    host = urllib.parse.urlsplit(url).netloc.lower()
    attempt = 0
    while True:
        throttle.wait(host)
        try:
            with opener(request, timeout=timeout) as response:
                status, body = response.getcode(), response.read()
                headers = _headers(response.headers)
        except urllib.error.HTTPError as exc:
            status, body, headers = exc.code, exc.read(), _headers(exc.headers or {})
        except (urllib.error.URLError, OSError):
            if attempt >= MAX_RETRIES:
                raise
            sleep(_retry_delay(attempt, None))
            attempt += 1
            continue
        if status in RETRY_STATUSES and attempt < MAX_RETRIES:
            sleep(_retry_delay(attempt, headers))
            attempt += 1
            continue
        return status, body, headers


def get_transport(transport):
    return transport if transport is not None else live_transport


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def response_date(headers):
    """The response's Date header as an ISO 8601 UTC string, or None."""
    value = (headers or {}).get('date')
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed.strftime('%Y-%m-%dT%H:%M:%SZ')


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def checked_at(headers, clock=None):
    """When a check happened: the pinned clock, else the response's own Date.

    Under replay the Date header is the one recorded with the fixture, so no
    output claims a check that did not run that day.
    """
    if clock is not None:
        return clock()
    return response_date(headers) or utc_now()


class ReplayTransport(object):
    """Serve recorded fixtures: `<name>.body` + `<name>.meta.json`.

    An unrecorded URL raises LookupError; a body whose sha256 differs from the
    sidecar raises ValueError. Lookups use the URL with contact parameters
    stripped, the same form the recorder stores.
    """

    def __init__(self, fixtures_dir):
        self.fixtures_dir = str(fixtures_dir)
        self.index = {}
        for name in sorted(os.listdir(self.fixtures_dir)):
            if not name.endswith('.meta.json'):
                continue
            path = os.path.join(self.fixtures_dir, name)
            with open(path, 'rb') as handle:
                meta = json.loads(handle.read().decode('utf-8'))
            key = strip_contact(meta['url'])
            if key in self.index:
                raise ValueError('two fixtures record the same URL: %s' % key)
            self.index[key] = (name[:-len('.meta.json')], meta)
        self.requested = []

    def __call__(self, url, timeout=None):
        key = strip_contact(url)
        self.requested.append(key)
        if key not in self.index:
            raise LookupError('no recorded response for %s' % key)
        name, meta = self.index[key]
        with open(os.path.join(self.fixtures_dir, name + '.body'), 'rb') as handle:
            body = handle.read()
        if sha256(body) != meta['body_sha256']:
            raise ValueError('recorded body digest mismatch for fixture %s' % name)
        return int(meta['status']), body, dict(meta.get('headers') or {})

    def recorded_date(self, url):
        name, meta = self.index[strip_contact(url)]
        return meta.get('date')
