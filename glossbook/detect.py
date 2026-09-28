"""Guess the language of the book's text, to catch a missing or wrong dc:language (calibre and
many converters write "en" for everything). Scripts decide first (kana, hangul, Han, Cyrillic,
Greek, Arabic/Hebrew); Latin-script text is scored by frequent function words."""
import re

from . import languages as L

# About a dozen very frequent words that are rare in the other languages listed.
STOPWORDS = {
    "en": "the and of to is was that with his her you it for not but have which",
    "it": "il di che non è la per una del della gli sono le si con anche più",
    "fr": "le les des est une dans pas que qui sur pour elle ne au avec était",
    "es": "el los las que del una por con para es pero más como está fue",
    "pt": "o os que não uma com do da em para são mas ele ela está foi",
    "de": "der die und nicht das ist ich sie mit den ein sich auch dem war",
    "nl": "de het een niet van en is dat ik zijn met op voor maar hij",
    "sv": "och att det som en på är inte för med har jag av till var",
    "da": "og at det som en på er ikke for med har jeg af til var",
    "pl": "i nie się na że to jest do w z jak ale co tak jego",
    "cs": "a se na že je to v s jak ale by jsem co tak jeho",
    "ro": "și în nu că la cu pe este un o mai din care ce sau",
    "ca": "el la i que no els les amb per és una del com però",
    "tr": "ve bir bu da de için ile ne çok gibi ama daha olan",
}
_WORDS = {k: set(v.split()) for k, v in STOPWORDS.items()}
_TOKEN = re.compile(r"[^\W\d_]+")


def _script(text):
    counts = {"kana": 0, "hangul": 0, "han": 0, "cyr": 0, "greek": 0, "rtl": 0, "latin": 0}
    for c in text:
        o = ord(c)
        if 0x3040 <= o <= 0x30FF:
            counts["kana"] += 1
        elif 0xAC00 <= o <= 0xD7AF:
            counts["hangul"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["han"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["cyr"] += 1
        elif 0x0370 <= o <= 0x03FF:
            counts["greek"] += 1
        elif 0x0590 <= o <= 0x06FF:
            counts["rtl"] += 1
        elif c.isalpha() and o < 0x0250:
            counts["latin"] += 1
    return counts


_SOURCE_SCRIPTS = {"zh": ("han", "kana"), "zh-hant": ("han", "kana"), "ja": ("han", "kana"),
                   "ko": ("hangul", "han"), "ru": ("cyr",), "uk": ("cyr",), "bg": ("cyr",), "el": ("greek",)}


def foreign(text, lang):
    """True if a block is mostly in a script the source language doesn't use (e.g. the Chinese
    paragraphs of a French–Chinese bilingual book)."""
    lang = L.base(lang)
    if lang == "sr":            # written in both Cyrillic and Latin
        return False
    c = _script(text)
    total = sum(c.values())
    if total < 2:
        return False
    own = sum(c[k] for k in _SOURCE_SCRIPTS.get(lang, ("latin",)))
    return own < 0.3 * total


def written_in(text, lang):
    """False only when text is clearly not in lang (checked by script: a Chinese guide written in
    Italian). Latin-script targets can't be told apart this way and always pass."""
    scripts = _SOURCE_SCRIPTS.get(L.base(lang))
    if not scripts or not text:
        return True
    c = _script(text)
    total = sum(c.values())
    return total < 10 or sum(c[k] for k in scripts) >= 0.5 * total


def guess(text):
    """Return (language code or None, confidence 0–1)."""
    c = _script(text)
    total = sum(c.values())
    if total < 200:
        return None, 0.0
    if c["kana"] > 0.05 * total:
        return "ja", 1.0
    if c["hangul"] > 0.3 * total:
        return "ko", 1.0
    if c["han"] > 0.3 * total:
        return "zh", 1.0
    if c["cyr"] > 0.5 * total:
        return ("uk" if any(ch in text for ch in "іїєґ") else "ru"), 0.9
    if c["greek"] > 0.5 * total:
        return "el", 1.0
    if c["rtl"] > 0.5 * total:
        return "ar", 0.5
    if c["latin"] < 0.5 * total:
        return None, 0.0
    tokens = [t.lower() for t in _TOKEN.findall(text)]
    scores = {k: sum(t in words for t in tokens) for k, words in _WORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if not tokens or s1 < 20:
        return None, 0.0
    return best, round(1 - s2 / s1, 2)


def sample(book, limit=20000):
    """Text of the book's body blocks, from the middle outwards (front matter is often in another
    language: copyright pages, English metadata)."""
    blocks = [b.text for b in book.blocks if not b.heading]
    mid = len(blocks) // 2
    out, n = [], 0
    for t in blocks[mid:] + blocks[:mid]:
        out.append(t)
        n += len(t)
        if n >= limit:
            break
    return " ".join(out)


_CLOSE = ({"da", "no", "nb", "nn", "sv"}, {"cs", "sk"}, {"hr", "sr", "bs"})


def _same_language(a, b):
    a, b = L.base(a).split("-")[0], L.base(b).split("-")[0]
    return a == b or any(a in g and b in g for g in _CLOSE)


def check_declared(book, declared):
    """Compare dc:language with the text. Returns (language to use, message or "")."""
    found, conf = guess(sample(book))
    if found and not declared:
        return found, (f"Note: the EPUB has no dc:language; the text looks {L.name(found)} "
                       "(use --source to override)")
    if found and declared and conf >= 0.5 and not _same_language(found, declared):
        return found, (f"Note: dc:language says {declared!r} but the text looks {L.name(found)}; using {found} "
                       f"(use --source {L.base(declared)} to keep the declared language)")
    return declared, ""
