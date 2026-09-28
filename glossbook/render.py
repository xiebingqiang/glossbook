"""Write results back into the XHTML: wrap glossed words in <ruby>, add a ¶ link after each
segment and a ¶ chapter guide after the heading; build the HTML of the note pages."""
import copy
import html
import posixpath
import re

from lxml import etree

from . import languages as L
from . import textnodes
from .epub import OPS_NS

NR_STYLE = "text-decoration:none;border:none;color:#888888"
BACK_STYLE = "text-decoration:none;color:#999999"
NOTES_MAX_BYTES = 150_000   # per note page: a ¶ tap loads the whole page, so huge pages are slow to open
EPUB_TYPE = f"{{{OPS_NS}}}type"

CSS = """
ruby.gbr { ruby-position: over; ruby-align: center; white-space: nowrap; }
ruby.gbr rt { ruby-align: center; letter-spacing: 0; font-size: 0.5em; font-weight: normal; font-style: normal; line-height: 1; text-indent: 0; }
ruby.gbr rt { color: #444444; border-bottom: 1px solid #999999; padding-bottom: 2px; margin-bottom: 1px; }
a.gb-nr, a.gb-nr:link, a.gb-nr:visited { text-decoration: none !important; border: none !important; color: #888888; font-size: 1.2em; line-height: 1; font-style: normal; font-weight: normal; }
h1 a.gb-nr, h2 a.gb-nr, h3 a.gb-nr, h4 a.gb-nr { font-size: 0.6em; vertical-align: middle; }
aside.gb-note { display: block; }
p.gb-zh, p.gb-gl, p.gb-cu, p.gb-kw { text-indent: 0; text-align: left; margin: 0; }
p.gb-zh { margin-top: 0.9em; padding-top: 0.5em; border-top: 1px solid #cccccc; font-size: 1em; }
p.gb-gl, p.gb-cu, p.gb-kw { font-size: 0.85em; line-height: 1.35; margin-top: 0.2em; }
p.gb-intro { text-indent: 0; text-align: right; margin: 0; }
span.gb-n { color: #555555; }
a.gb-back, a.gb-back:link, a.gb-back:visited { color: #999999; text-decoration: none !important; font-size: 0.85em; }
"""


def esc(s):
    return html.escape(s or "", quote=False)


def ns_of(el):
    q = etree.QName(el)
    return f"{{{q.namespace}}}" if q.namespace else ""


def notes_name(doc_path, part=0):
    stem = posixpath.basename(doc_path).rsplit(".", 1)[0]
    return f"gb-notes-{stem}{f'-{part + 1}' if part else ''}.xhtml"


class NotePages:
    """The notes of one content document go to note pages of about NOTES_MAX_BYTES each.
    pages: {file name: (doc index, part, [aside HTML])}."""

    def __init__(self, book):
        self.book, self.pages, self.size = book, {}, {}

    def current(self, doc):
        """File name of the page the next notes of this document go to."""
        parts = [(part, name) for name, (d, part, _) in self.pages.items() if d == doc]
        part, name = max(parts, default=(-1, None))
        if name is None or self.size[name] >= NOTES_MAX_BYTES:
            name = notes_name(self.book.docs[doc].path, part + 1)
            self.pages[name], self.size[name] = (doc, part + 1, []), 0
        return name

    def add(self, name, aside_html):
        self.pages[name][2].append(aside_html)
        self.size[name] += len(aside_html.encode("utf-8"))


def marker(ns, sid, href):
    a = etree.Element(f"{ns}a", {"class": "gb-nr", "style": NR_STYLE, EPUB_TYPE: "noteref",
                                 "id": f"r-{sid}", "href": f"{href}#n-{sid}"})
    a.text = " ¶"
    return a


def ruby_maker(ns, gloss):
    def make(word):
        r = etree.Element(f"{ns}ruby", {"class": "gbr"})
        span = etree.SubElement(r, f"{ns}span")
        span.text = word
        rt = etree.SubElement(r, f"{ns}rt")
        rt.text = gloss
        return r
    return make


def gloss_line(p, target):
    g = p.gloss
    line = f"<b>{esc(g.w)}</b> {esc(g.g)}"
    if g.note:
        line += f' <span class="gb-n">{"（" + esc(g.note) + "）" if L.is_cjk(target) else "(" + esc(g.note) + ")"}</span>'
    return line


def note_glosses(placed):
    """Glosses listed in the note: a ruby with nothing more to say (no note) is not repeated."""
    return [p for p in placed or [] if not (p.ruby and not p.gloss.note)]


def seg_rows(result, placed, target, culture_label, show_tr=True):
    rows = [("gb-zh", esc(result.tr))] if show_tr and result.tr else []
    placed = note_glosses(placed)
    if placed:
        rows.append(("gb-gl", "<br/>".join(gloss_line(p, target) for p in placed)))
    if result.cu:
        rows.append(("gb-cu", f"<b>{esc(culture_label)}</b> {esc(result.cu)}"))
    return rows


def intro_rows(intro, target):
    ui, sep = L.ui(target), L.list_sep(target)
    rows = [("gb-zh", f"<b>{esc(ui['summary'])}</b> {esc(intro.get('summary', ''))}")]
    if intro.get("who"):
        rows.append(("gb-gl", f"<b>{esc(ui['who'])}</b> " + sep.join(esc(w) for w in intro["who"])))
    if intro.get("kw"):
        rows.append(("gb-kw", f"<b>{esc(ui['kw'])}</b> " +
                     sep.join(f"<b>{esc(k['w'])}</b> {esc(k['g'])}" for k in intro["kw"])))
    return rows


def aside(sid, rows, back_href):
    back = f'  <a class="gb-back" style="{BACK_STYLE}" href="{back_href}#r-{sid}">↩</a>' if back_href else ""
    rows = rows[:-1] + [(rows[-1][0], rows[-1][1] + back)]
    body = "".join(f'<p class="{c}">{h}</p>' for c, h in rows)
    return f'<aside class="gb-note" epub:type="footnote" id="n-{sid}">{body}</aside>'


def segs_by_block(segs):
    """{block index: [segments with a part in that block]} (a verse segment is in several blocks)."""
    out = {}
    for seg in segs:
        for bi in dict.fromkeys(b for b, _, _ in seg.spans()):
            out.setdefault(bi, []).append(seg)
    return out


def has_note(r, placed, show_tr=True):
    """A segment gets a ¶ if it was generated (with a translation, when translations are shown) and
    its note has something in it."""
    if r is None:
        return False
    return bool(r.tr) if show_tr else bool(placed or r.cu)


def annotate_block(el, bi, segs, outcome, placed, notes_href, show_tr=True):
    """Insert the rubies that fall in block bi, and the ¶ links of segments ending in it, into el.
    Returns [(sid, seg, result)] for the ¶ links inserted."""
    ns = ns_of(el)
    done = []
    for seg in segs:
        r = outcome.results.get(seg.id)
        if r is None or (show_tr and not r.tr):
            continue
        sid = f"gb{seg.id}"
        for p in placed.get(seg.id, []):
            if p.ruby and p.span and p.block == bi:
                p.ruby = textnodes.wrap(el, p.span[0], p.span[1], ruby_maker(ns, p.gloss.g))
        # the ¶ goes in the segment's last block, so every ruby of the segment is settled by now
        if seg.block == bi and has_note(r, note_glosses(placed.get(seg.id)), show_tr):
            textnodes.insert_at(el, seg.end, marker(ns, sid, notes_href))
            done.append((sid, seg, r))
    return done


def intro_anchor(book, ch):
    """Block index of the chapter heading (within the first 3 blocks) that gets the guide ¶, or None
    (a new paragraph is then inserted before the first block)."""
    for bi in range(ch.start, min(ch.end, ch.start + 3)):
        if book.blocks[bi].heading:
            return bi
    return None


def apply(book, chapters, plans, outcome, placed, s):
    """Modify the XHTML trees in book in place. Returns NotePages.pages."""
    target, label = s.target, L.ui(s.target)["culture"]
    notes = NotePages(book)
    for ch in chapters:
        by_block = segs_by_block(plans.get(ch.index, []))
        intro = outcome.intros.get(ch.index)
        if intro and intro.get("summary") and ch.end > ch.start:
            hb = intro_anchor(book, ch)
            b = book.blocks[hb if hb is not None else ch.start]
            href = notes.current(b.doc)
            sid = f"gbc{ch.index}-intro"
            ns = ns_of(b.el)
            if hb is not None:
                textnodes.insert_at(b.el, len(b.text), marker(ns, sid, href))
            else:
                p = etree.Element(f"{ns}p", {"class": "gb-intro"})
                p.append(marker(ns, sid, href))
                b.el.addprevious(p)
            notes.add(href, aside(sid, intro_rows(intro, target), posixpath.basename(book.docs[b.doc].path)))
        for bi, segs in by_block.items():
            b = book.blocks[bi]
            doc_file = posixpath.basename(book.docs[b.doc].path)
            href = notes.current(b.doc)
            for sid, seg, r in annotate_block(b.el, bi, segs, outcome, placed, href, s.translation):
                rows = seg_rows(r, placed.get(seg.id, []), target, label, s.translation)
                notes.add(href, aside(sid, rows, doc_file))
    return notes.pages


def notes_page(title, asides, lang, css_href):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="{OPS_NS}" lang="{lang}" xml:lang="{lang}">\n'
            f'<head><meta charset="utf-8"/><title>{esc(title)}</title>'
            f'<link href="{css_href}" rel="stylesheet" type="text/css"/></head>\n'
            f'<body>\n{chr(10).join(asides)}\n</body>\n</html>\n')


def block_html(el, bi, segs, outcome, placed, show_tr=True):
    """For the preview: annotate a copy of the block. Returns (HTML, [(sid, seg, result)])."""
    c = copy.deepcopy(el)
    c.tail = None
    done = annotate_block(c, bi, segs, outcome, placed, "", show_tr)
    s = etree.tostring(c, encoding="unicode")
    s = re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", s)
    return s, done
