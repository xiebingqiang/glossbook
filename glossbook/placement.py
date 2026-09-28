"""Build-time decision for each gloss: ruby (small print above the word), note only, or hidden.

- Only expressions above the reader's level get a ruby (for a C2 reader: C1 and C2);
  expressions two or more levels below the reader are hidden entirely (so building for a higher
  level automatically thins things out).
- Density: on average at most one ruby per `density` words (a small head start is allowed);
  within a segment, higher-level expressions go first.
- At most `repeat` rubies per lemma.
- Glosses too long to fit above a word stay in the note (a long ruby would stretch the line).
"""
from dataclasses import dataclass

from . import languages as L
from . import match, segment
from .config import LEVELS


@dataclass
class Placed:
    gloss: object
    span: tuple | None     # span in the block's plain text; None = not found (note only)
    ruby: bool = False
    block: int = None      # the block the span is in


def rank(level, default):
    return LEVELS.index(level) if level in LEVELS else default


def gloss_fits(g, target):
    limit = 8 if (L.is_cjk(target) or L.base(target) == "ko") else 25
    return len(g) <= limit


def _locate(book, seg, g, taken, lang):
    for bi, start, end in seg.spans():
        spans = taken.setdefault(bi, [])
        span = match.find(book.blocks[bi].text, g.w, start, end, spans, lang)
        if span:
            spans.append(span)
            return Placed(g, span, block=bi)
    return Placed(g, None)


def choose(book, plans, results, s, lang):
    """{seg.id: [Placed]} in text order."""
    reader = LEVELS.index(s.level)
    ruby_from = reader + 1 if reader + 1 < len(LEVELS) else reader - 1   # C2 reader: C1 and C2
    counts, taken, placed = {}, {}, {}
    words, used = 0.0, 0
    for ch_index in sorted(plans):
        for seg in plans[ch_index]:
            r = results.get(seg.id)
            if r is None:
                continue
            words += segment.units(seg.text, lang)
            items = []
            for g in r.gl:
                if rank(g.level, reader + 1) < reader - 1:
                    continue
                items.append(_locate(book, seg, g, taken, lang))
            allowed = int(words / s.density + 1) - used
            cands = [p for p in items if p.span and rank(p.gloss.level, reader + 1) >= ruby_from
                     and gloss_fits(p.gloss.g, s.target)]
            cands.sort(key=lambda p: -rank(p.gloss.level, reader + 1))
            for p in cands:
                if allowed <= 0:
                    break
                lemma = (p.gloss.lemma or p.gloss.w).lower()
                if counts.get(lemma, 0) >= s.repeat:
                    continue
                p.ruby = True
                counts[lemma] = counts.get(lemma, 0) + 1
                allowed -= 1
                used += 1
            items.sort(key=lambda p: (p.block, p.span[0]) if p.span else (float("inf"), 0))
            placed[seg.id] = items
    return placed


def stats(placed, plans, lang):
    words = sum(segment.units(sg.text, lang) for segs in plans.values() for sg in segs)
    n_gl = sum(len(v) for v in placed.values())
    n_ruby = sum(p.ruby for v in placed.values() for p in v)
    return {"words": words, "glosses": n_gl, "rubies": n_ruby,
            "gloss_per_100": round(n_gl * 100 / words, 1) if words else 0,
            "ruby_per_100": round(n_ruby * 100 / words, 1) if words else 0}
