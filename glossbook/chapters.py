"""Chapters from the table of contents (EPUB3 nav or EPUB2 NCX). Each TOC entry is located at a
text block; a chapter is every block between two consecutive entries. Text before the first entry
becomes chapter 0 (front matter). A broken TOC falls back to one chapter per file, then to
h1–h3 headings."""
import re
from dataclasses import dataclass

from . import epub
from .segment import units
from .textnodes import local

FRONT_MATTER = "(front matter)"
BOILERPLATE = re.compile(r"project gutenberg.*licen[cs]e", re.I)   # left out unless selected by number


@dataclass
class Chapter:
    index: int
    title: str
    start: int         # index into book.blocks, inclusive
    end: int           # exclusive
    words: int = 0


def open_book(path):
    book = epub.load(path)
    make_chapters(book)
    return book


def _position(book, path, anchor):
    """Index of the first block at or after a TOC entry (or containing its anchor), or None."""
    di = next((i for i, d in enumerate(book.docs) if d.path == path), None)
    if di is None:
        return None
    target_order = 0
    if anchor:
        tree = book.docs[di].tree
        if tree is None:
            return None
        root = tree.getroot()
        el = next((e for e in root.iter() if anchor in (e.get("id"), e.get("name"))), None)
        if el is not None:
            ancestors = set(el.iterancestors())
            for bi, b in enumerate(book.blocks):
                if b.doc == di and (b.el in ancestors or b.el is el):
                    return bi
            target_order = next(i for i, e in enumerate(root.iter()) if e is el)
    for bi, b in enumerate(book.blocks):
        if (b.doc == di and b.order >= target_order) or b.doc > di:
            return bi
    return None


def _first_heading(book, bi, short=False):
    """The block's text if it is a heading (or, with short=True, a heading-like line: at most 6
    words, not ending like a sentence unless it is a number such as "1.")."""
    b = book.blocks[bi]
    text = " ".join(b.text.split())
    title_like = len(text.split()) <= 6 and len(text) <= 40 and \
        (not text.endswith((".", "!", "?", "。")) or text[:-1].isdigit())
    return text[:60] if b.heading or (short and title_like) else ""


def _from_toc(book):
    starts = []   # [(block_index, title)]
    for label, path, anchor in book.toc:
        pos = _position(book, path, anchor)
        if pos is not None and pos not in {s for s, _ in starts}:
            starts.append((pos, label))
    return starts


def _from_files(book):
    starts, seen = [], set()
    for bi, b in enumerate(book.blocks):
        if b.doc not in seen:
            seen.add(b.doc)
            starts.append((bi, _first_heading(book, bi, short=True) or book.docs[b.doc].path.rsplit("/", 1)[-1]))
    return starts


def _from_headings(book):
    return [(bi, _first_heading(book, bi)) for bi, b in enumerate(book.blocks)
            if b.heading and local(b.el.tag) in ("h1", "h2", "h3")]


def _good(book, starts, check_largest=True):
    """A broken TOC (e.g. a single entry for the license at the end) leaves more than half the text
    before its first entry; a split by file/heading that is too coarse has a chapter over 60%."""
    if not starts:
        return False
    sizes = [len(b.text) for b in book.blocks]
    total = sum(sizes)
    if total < 3000:
        return True
    bounds = sorted({0, *(s for s, _ in starts), len(sizes)})
    parts = [sum(sizes[a:b]) for a, b in zip(bounds, bounds[1:], strict=False)]
    before = sum(sizes[:min(s for s, _ in starts)])
    return before <= 0.5 * total and (not check_largest or max(parts) <= 0.6 * total)


def make_chapters(book):
    """TOC first (any chapter size: a Gutenberg license can be longer than the story);
    otherwise one chapter per file; otherwise h1–h3 headings. A TOC with a chapter over 60% of the
    book (e.g. a single entry "Start") is kept only if the fallbacks can't do better."""
    starts = _from_toc(book)
    fallback = (st for st in (_from_files(book), _from_headings(book)) if _good(book, st))
    if not _good(book, starts, check_largest=False):
        starts = next(fallback, None) or _from_files(book)
    elif not _good(book, starts):
        starts = next(fallback, None) or starts
    starts = sorted(starts)
    has_front = bool(starts) and starts[0][0] > 0
    if has_front:
        starts.insert(0, (0, FRONT_MATTER))
    lang = book.lang or "en"
    chapters = []
    for i, (s, title) in enumerate(starts):
        e = starts[i + 1][0] if i + 1 < len(starts) else len(book.blocks)
        ch = Chapter(i if has_front else i + 1, title or _first_heading(book, s) or f"#{i}", s, e)
        ch.words = sum(units(b.text, lang) for b in book.blocks[s:e] if not b.heading)
        chapters.append(ch)
    book.chapters = chapters


def select(book, spec):
    """'1-3,5,8-' / 'all' / None -> chapters. Numbers are the ones shown by `inspect`. 'all' leaves
    out boilerplate such as the Project Gutenberg license."""
    if not spec or spec == "all":
        return [c for c in book.chapters if not BOILERPLATE.search(c.title)] or list(book.chapters)
    idx = {c.index: c for c in book.chapters}
    top = max(idx) if idx else 0
    chosen = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                rng = range(int(a) if a else 0, (int(b) if b else top) + 1)
            else:
                rng = [int(part)]
        except ValueError:
            raise ValueError(f"cannot parse chapter range {part!r} (example: 1-3,5,8-)") from None
        chosen += [idx[i] for i in rng if i in idx and idx[i] not in chosen]
    if not chosen:
        raise ValueError(f"{spec!r} selects no chapters (available: {min(idx)}–{top})")
    return sorted(chosen, key=lambda c: c.index)
