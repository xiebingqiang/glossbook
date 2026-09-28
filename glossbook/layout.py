"""Which blocks of a chapter get notes, and how blocks become note segments.

- Headings, bare numbers (stanza or chapter numbers: "1", "IV.", "[3]") and blocks in another script
  (the translation paragraphs of a bilingual book) are not annotated.
- Verse: many books put every line of a poem in its own <p>. A run of short lines that mostly don't
  end a sentence is joined and segmented as one text, so a note covers a sentence or clause of the
  poem instead of one line. Such a segment has several parts (one per line); its ¶ goes after the
  last one.
"""
import re

from . import detect, segment

VERSE_LINE_MAX = 14      # a line of verse has at most this many words
VERSE_MIN_LINES = 4
VERSE_OPEN_SHARE = 0.25  # at least this share of the lines doesn't end a sentence
LINE_JOIN = " / "        # how line breaks are shown to the model
VERSE_PUNCT_SHARE = 0.3  # ...and at least this share ends with punctuation (unlike a list of names)
_NUMBER = re.compile(r"[\W\d_]*|\W*[IVXLCDM]+\W*|[【\[〔（(][^】\]〕）)]{1,8}[】\]〕）)]")   # "3", "IV.", "【注释】"
_ENDS = re.compile(r"[.!?…。！？][\"'”’»«›‹)\]」』]*\s*$")
_PUNCT_END = re.compile(r"[^\w\s]\s*$")
_DIALOGUE = re.compile(r"\s*[“\"«»„‚‘'—–-「『]")


def _number(block):
    return not block.heading and bool(_NUMBER.fullmatch(block.text.strip()))


def annotatable(block, lang):
    return not block.heading and not _number(block) and not detect.foreign(block.text.strip(), lang)


def _is_line(block, lang):
    return "\n" not in block.text.strip() and segment.units(block.text, lang) <= VERSE_LINE_MAX


def _runs(book, bis, lang):
    """Split consecutive annotatable block indexes into runs: verse runs (several blocks) and single
    prose blocks. Yields lists of block indexes."""
    run = []

    def flush():
        lines = [book.blocks[i].text for i in run]
        n = len(lines)
        verse = n >= VERSE_MIN_LINES \
            and sum(not _ENDS.search(t) for t in lines) >= VERSE_OPEN_SHARE * n \
            and sum(bool(_PUNCT_END.search(t)) for t in lines) >= VERSE_PUNCT_SHARE * n \
            and sum(bool(_DIALOGUE.match(t)) for t in lines) < 0.5 * n      # dialogue, not verse
        if verse:
            yield list(run)
        else:
            yield from ([i] for i in run)
        run.clear()

    for bi in bis:
        b = book.blocks[bi]
        # stanza numbers between lines don't break a run
        joins = run and b.doc == book.blocks[run[-1]].doc and \
            all(_number(book.blocks[i]) for i in range(run[-1] + 1, bi))
        if run and not (joins and _is_line(b, lang)):
            yield from flush()
        if _is_line(b, lang):
            run.append(bi)
        else:
            yield [bi]
    if run:
        yield from flush()


def _verse_segments(book, run, lang, per_note, max_words):
    """Segment the joined lines. Returns [(parts, text)], parts = [(block, start, end)]."""
    offsets, pieces, pos = [], [], 0
    for bi in run:
        offsets.append(pos)
        pieces.append(book.blocks[bi].text)
        pos += len(pieces[-1]) + 1
    joined = "\n".join(pieces)
    out = []
    for s, e in segment.segments(joined, lang, per_note, max_words):
        spans = segment.split_long(joined, s, e, lang, 2 * max_words) if per_note != "clause" else [(s, e)]
        for s2, e2 in spans:
            parts = []
            for bi, off, text in zip(run, offsets, pieces, strict=True):
                a, b = max(s2, off) - off, min(e2, off + len(text)) - off
                if a < b:
                    a, b = segment._trim(text, a, b)
                    if any(c.isalnum() for c in text[a:b]):
                        parts.append((bi, a, b))
            if parts:
                shown = LINE_JOIN.join(segment.normalize(book.blocks[bi].text[a:b]) for bi, a, b in parts)
                out.append((parts, shown))
    return out


def chapter_segments(book, ch, lang, per_note, max_words):
    """[(parts, text)] for a chapter, in reading order."""
    bis = [bi for bi in range(ch.start, ch.end) if annotatable(book.blocks[bi], lang)]
    out = []
    for run in _runs(book, bis, lang):
        if len(run) > 1:
            out += _verse_segments(book, run, lang, per_note, max_words)
            continue
        text = book.blocks[run[0]].text
        out += [([(run[0], s, e)], segment.normalize(text[s:e]))
                for s, e in segment.segments(text, lang, per_note, max_words)]
    return out
