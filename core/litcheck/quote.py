"""Does a quoted passage appear in a text? A deterministic, versioned answer.

Normalisation `q1`, applied to quote and text alike:
  1. Unicode NFKC;
  2. curly single and double quotes become straight ones;
  3. the dash family (U+2010 to U+2015, U+2212) becomes '-';
  4. every run of whitespace becomes one space, and the ends are stripped.
Case is kept. Line-end hyphens are not joined. On text that differs only in
whitespace this agrees with peerpanel's grounding rule (`" ".join(s.split())`).

`q1` is pinned: any change to normalisation needs a dated CHANGES entry and a
new version name, because offsets recorded under `q1` mean `q1` text.

Matching runs on the raw md5-verified text as fetched, never on a sanitised
copy. Offsets are code-point positions in the normalised text.
"""
import re
import unicodedata

NORMALISATION_VERSION = 'q1'

FOUND = 'FOUND'
NOT_FOUND = 'NOT_FOUND'
TOO_SHORT = 'TOO_SHORT'
NOT_CHECKABLE = 'NOT_CHECKABLE'
VERDICTS = (FOUND, NOT_FOUND, TOO_SHORT, NOT_CHECKABLE)

MIN_QUOTE_CHARS = 20

QUOTE_MAP = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"',
}
DASH_MAP = dict((code, '-') for code in list(range(0x2010, 0x2016)) + [0x2212])
TRANSLATION = dict(QUOTE_MAP)
TRANSLATION.update(DASH_MAP)
PARAGRAPH_BREAK = re.compile(r'\n[ \t\r\f\v]*\n')


def normalise(text):
    text = unicodedata.normalize('NFKC', text)
    text = text.translate(TRANSLATION)
    return ' '.join(text.split())


def _paragraph_starts(text):
    """Offsets in the normalised text where each raw paragraph begins.

    Paragraphs are split on blank lines before normalising. Returns None when
    the joined paragraphs do not reproduce normalise(text) exactly, so a
    paragraph index is never reported against misaligned offsets.
    """
    starts = []
    pieces = []
    cursor = 0
    for index, raw in enumerate(PARAGRAPH_BREAK.split(text)):
        piece = normalise(raw)
        if not piece:
            continue
        if pieces:
            cursor += 1
        starts.append((cursor, index))
        pieces.append(piece)
        cursor += len(piece)
    if ' '.join(pieces) != normalise(text):
        return None
    return starts


def check(quote, text):
    """Return a dict: verdict, offsets, paragraph, casefold_found, normalisation.

    FOUND: the normalised quote occurs in the normalised text; `offsets` is
    [start, end) of the first occurrence and `paragraph` the index of the
    blank-line-separated paragraph it starts in. NOT_FOUND otherwise.
    TOO_SHORT: under MIN_QUOTE_CHARS characters after normalising; nothing is
    searched. `casefold_found` is a secondary flag: the quote occurs when case
    is ignored. NOT_CHECKABLE is the caller's verdict when no text exists.
    """
    result = {'verdict': None, 'offsets': None, 'paragraph': None,
              'casefold_found': None, 'normalisation': NORMALISATION_VERSION}
    needle = normalise(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        result['verdict'] = TOO_SHORT
        return result
    haystack = normalise(text)
    result['casefold_found'] = needle.casefold() in haystack.casefold()
    start = haystack.find(needle)
    if start < 0:
        result['verdict'] = NOT_FOUND
        return result
    result['verdict'] = FOUND
    result['offsets'] = [start, start + len(needle)]
    starts = _paragraph_starts(text)
    if starts is not None:
        for offset, index in starts:
            if offset <= start:
                result['paragraph'] = index
    return result


def not_checkable():
    return {'verdict': NOT_CHECKABLE, 'offsets': None, 'paragraph': None,
            'casefold_found': None, 'normalisation': NORMALISATION_VERSION}
