#!/usr/bin/env python3
"""Record one live response as a replay fixture.

    python3 core/tools/record_fixture.py <name> <url> [--dir core/tests/fixtures]

Fetches <url> once through litcheck's live transport and writes
<name>.body (the verbatim bytes) and <name>.meta.json (url, status, date,
headers, body_sha256, provenance). The stored URL has its email, mailto and
tool parameters removed; Set-Cookie and any header carrying the contact
address are dropped; a body that contains the contact address is refused.
Never overwrites an existing fixture.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), ''))

from litcheck import transport  # noqa: E402

DEFAULT_DIR = os.path.join(os.path.dirname(HERE), 'tests', 'fixtures')
NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_.-]*$')
MAX_BODY = 2 * 1024 * 1024
DROPPED_HEADERS = ('set-cookie',)


def parser():
    result = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    result.add_argument('name')
    result.add_argument('url')
    result.add_argument('--dir', default=DEFAULT_DIR)
    return result


def clean_headers(headers, address):
    kept = {}
    for key, value in sorted(headers.items()):
        if key.lower() in DROPPED_HEADERS:
            continue
        if address and address.lower() in value.lower():
            continue
        kept[key.lower()] = value
    return kept


def record(name, url, directory, fetch=None, today=None):
    if not NAME_PATTERN.match(name):
        raise SystemExit('fixture name must be lower-case letters, digits, dot, dash, underscore')
    body_path = os.path.join(directory, name + '.body')
    meta_path = os.path.join(directory, name + '.meta.json')
    for path in (body_path, meta_path):
        if os.path.exists(path):
            raise SystemExit('refusing to overwrite %s' % path)
    stored_url = transport.strip_contact(url)
    try:
        status, body, headers = (fetch or transport.live_transport)(stored_url)
    except OSError as exc:
        raise SystemExit('could not fetch %s: %s' % (stored_url, exc))
    if len(body) > MAX_BODY:
        raise SystemExit('response is %d bytes; fixtures stay under 2 MB' % len(body))
    address = transport.contact()
    if address and address.lower().encode('utf-8') in body.lower():
        raise SystemExit('the response body contains the contact address; not recorded')
    date = transport.response_date(headers) or transport.utc_now()
    meta = {
        'url': stored_url,
        'status': status,
        'date': date,
        'headers': clean_headers(headers, address),
        'body_sha256': transport.sha256(body),
        'provenance': 'recorded live %s by core/tools/record_fixture.py'
                      % (today or transport.utc_now()[:10]),
    }
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(body_path, 'wb') as handle:
        handle.write(body)
    with open(meta_path, 'w') as handle:
        handle.write(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return meta


def main(argv=None):
    args = parser().parse_args(argv)
    meta = record(args.name, args.url, args.dir)
    print('%s: HTTP %s, %s, sha256 %s' % (args.name, meta['status'], meta['date'],
                                          meta['body_sha256']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
