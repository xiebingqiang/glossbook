"""Find a glossed expression in the original text: apostrophes and quotes are unified, whitespace
may differ, case-sensitive first and then case-insensitive; word boundaries are required except
for Chinese/Japanese."""
import re

from . import languages as L

_APOS = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "“": '"', "”": '"', "«": '"', "»": '"'})


def norm(s):
    """Same-length replacement, so offsets are preserved."""
    return s.translate(_APOS)


def _pattern(word, lang):
    parts = [re.escape(p) for p in norm(word).split()]
    if not parts:
        return None
    body = r"\s+".join(parts)
    if L.is_cjk(lang):
        return body
    left = r"(?<!\w)" if re.match(r"\w", parts[0][:1] or "") else ""
    right = r"(?!\w)" if re.search(r"\w$", word.strip()) else ""
    return left + body + right


def find(text, word, lo, hi, taken=(), lang="en"):
    """First occurrence of word in text[lo:hi] that doesn't overlap any span in taken.
    Returns (start, end) or None."""
    pat = _pattern(word, lang)
    if pat is None:
        return None
    nt = norm(text)
    for flags in (0, re.IGNORECASE):
        for m in re.compile(pat, flags).finditer(nt, lo, hi):
            s, e = m.span()
            if all(e <= a or s >= b for a, b in taken):
                return s, e
    return None
