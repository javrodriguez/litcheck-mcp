"""The core's unittest suite: offline unless LITCHECK_NETWORK_TESTS=1.

Importing this package replaces socket.socket.connect with a function that
raises, so a test that reaches for the network fails instead of quietly
depending on it. Shared helpers live here too.
"""
import os
import socket

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(HERE)
REPO = os.path.dirname(CORE)
FIXTURES = os.path.join(HERE, 'fixtures')
NETWORK = os.environ.get('LITCHECK_NETWORK_TESTS') == '1'

# The worked example: a CC BY editorial (Lotufo PA, Sao Paulo Med J 2016;134(3):185-6).
PAPER_PMCID = 'PMC10496602'
PAPER_PMID = '27355798'
PAPER_DOI = '10.1590/1516-3180.2016.1344090516'
TRUE_QUOTE = 'Arteriosclerosis consists of functional depletion of large-artery elasticity.'
CHANGED_QUOTE = 'Arteriosclerosis consists of functional depletion of small-artery elasticity.'
RETRACTED_PMCID = 'PMC12829825'
NOT_OA_PMCID = 'PMC13599058'
ABSENT_PMCID = 'PMC13632646'
NOT_IN_PMC_DOI = '10.1016/s0140-6736(97)11096-0'
FIXTURE_DAY = '2026-10-03T21:32:25Z'


def _blocked(*args, **kwargs):
    raise RuntimeError('network access attempted during an offline test '
                       '(set LITCHECK_NETWORK_TESTS=1 to allow it)')


if not NETWORK:
    socket.socket.connect = _blocked


def replay():
    from litcheck.transport import ReplayTransport
    return ReplayTransport(FIXTURES)


def pinned_clock(value=FIXTURE_DAY):
    return lambda: value


def has_fixture(url):
    from litcheck.transport import strip_contact
    try:
        return strip_contact(url) in replay().index
    except OSError:
        return False
