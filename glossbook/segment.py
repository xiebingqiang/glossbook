"""Sentence splitting, splitting long sentences into clauses at punctuation, and grouping by
per_note. Every function returns character spans [(start, end)] into the original text."""
import re

from . import languages as L

# a dash that ends a line (verse: "Nebelstreif. –") stays with the sentence before it
_END_SPACE = re.compile(r"[.!?…]+[\"'”’»«›‹)\]]*(?:[ \t]*[–—](?=[ \t]*\n))?(?=\s)")
_END_CJK = re.compile(r"[。！？!?…]+[」』”’）)\]》〉]*")
_OPENERS = "“\"«‹¿¡‘'([—–-「『《"
_CUT_STRONG = re.compile(r"[;:](?=\s)|\s[—–](?=\s)|[；：]")
_CUT_WEAK = re.compile(r",(?=\s)|[，、]|\n")   # \n: a line break (<br/> or a line of verse)
MERGE_MAX = 6   # in clause mode, adjacent sentences of <= 6 words each are merged


def units(text, lang):
    """Length in words. Chinese/Japanese have no spaces: about 2 characters count as 1 word."""
    if L.is_cjk(lang):
        n = sum(1 for c in text if not c.isspace() and c.isalnum())
        return (n + 1) // 2
    return len(text.split())


def _trim(text, s, e):
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _is_abbrev(before, lang):
    """before: the text up to a period. Don't split when its last word is an abbreviation or an initial."""
    words = before.split()
    if not words:
        return False
    last = words[-1].lstrip("(\"'“‘«")
    if len(last) == 1 and last.isupper():      # J. K. Rowling
        return True
    return last.lower() in L.abbreviations(lang)


def sentences(text, lang):
    spans, start = [], 0
    if L.is_cjk(lang):
        for m in _END_CJK.finditer(text):
            spans.append((start, m.end()))
            start = m.end()
    else:
        cased = L.has_case(lang)
        for m in _END_SPACE.finditer(text):
            rest = text[m.end():].lstrip()
            if not rest:
                continue
            if cased and not (rest[0].isupper() or rest[0].isdigit() or rest[0] in _OPENERS):
                continue
            if m.group().startswith(".") and len(m.group().rstrip("\"'”’»«›‹)] \t–—")) == 1 \
                    and _is_abbrev(text[start:m.start()], lang):
                continue
            spans.append((start, m.end()))
            start = m.end()
    spans.append((start, len(text)))
    out = [_trim(text, s, e) for s, e in spans]
    return [(s, e) for s, e in out if e > s and any(c.isalnum() for c in text[s:e])]


def _cut_points(text, s, e, pattern):
    return [m.end() for m in pattern.finditer(text, s, e) if s < m.end() < e]


def split_long(text, s, e, lang, max_words, min_words=4):
    """Split a sentence longer than max_words at ; : or a dash (commas as a second choice) until each
    piece has <= max_words. Returns the sentence unchanged if it can't be split."""
    if units(text[s:e], lang) <= max_words:
        return [(s, e)]
    mid = units(text[s:e], lang) / 2
    for pattern in (_CUT_STRONG, _CUT_WEAK):
        best = None
        for c in _cut_points(text, s, e, pattern):
            left, right = units(text[s:c], lang), units(text[c:e], lang)
            balanced = best is None or abs(left - mid) < abs(best[1] - mid)
            if left >= min_words and right >= min_words and balanced:
                best = (c, left)
        if best:
            c = best[0]
            a, b = _trim(text, s, c), _trim(text, c, e)
            return split_long(text, *a, lang, max_words, min_words) + \
                split_long(text, *b, lang, max_words, min_words)
    return [(s, e)]


def _merge_short(text, spans, lang, max_words):
    out = []
    for s, e in spans:
        if out:
            ps, pe = out[-1]
            a, b = units(text[ps:pe], lang), units(text[s:e], lang)
            if a <= MERGE_MAX and b <= MERGE_MAX and a + b <= max_words:
                out[-1] = (ps, e)
                continue
        out.append((s, e))
    return out


def segments(text, lang, per_note="clause", max_words=25):
    """A text block -> note segments. per_note: clause / 1 / 2 / 3 (sentences per note) / para (whole block)."""
    if not text.strip():
        return []
    if per_note == "para":
        return [_trim(text, 0, len(text))]
    sents = sentences(text, lang)
    if per_note == "clause":
        pieces = [p for s, e in sents for p in split_long(text, s, e, lang, max_words)]
        return _merge_short(text, pieces, lang, max_words)
    n = int(per_note)
    return [(sents[i][0], sents[min(i + n, len(sents)) - 1][1]) for i in range(0, len(sents), n)]


def normalize(s):
    """Text as sent to the model: whitespace collapsed."""
    return " ".join(s.split())
