"""Merge the annotated sample EPUBs into one demo EPUB, with a divider page before each book.

Each book keeps its own files under its own folder (relative links stay valid); the OPF, nav and
NCX are rebuilt. Usage: python3 samples/merge.py -> samples/glossbook-sample.epub
"""
import html
import posixpath
import zipfile
from pathlib import Path

from lxml import etree
from make_sources import CONTAINER

HERE = Path(__file__).resolve().parent
BOOKS = HERE / "books"
OUT = HERE / "glossbook-sample.epub"
OPF_NS = "http://www.idpf.org/2007/opf"
NS = {"o": OPF_NS, "dc": "http://purl.org/dc/elements/1.1/", "x": "http://www.w3.org/1999/xhtml"}

# output file, divider heading, what the part shows, settings used
PARTS = [
    ("en.zh-B1.epub", "English → 中文 · B1",
     "Dickens and two poems. Rubies over hard words, a ¶ after each clause with the translation and "
     "notes (“as dead as a door-nail”, ’Change), a chapter guide ¶ after each title. Verse: lines "
     "are joined into sentences, archaic words (thee, hath, ow’st) are glossed.",
     "--target zh --level B1"),
    ("ja.zh-B1.epub", "日本語 → 中文 · B1",
     "Akutagawa, “The Spider’s Thread”. Japanese segmentation, meanings of words and honorific forms, "
     "Buddhist terms (極楽, 三途の河) explained in the notes.",
     "--target zh --level B1"),
    ("it.en-A2.epub", "Italiano → English · A2",
     "Collodi, Pinocchio, chapter I. The A2 preset: short clauses, many rubies (one per ~9 words).",
     "--target en --level A2"),
    ("fr.en-B1.epub", "Français → English · B1",
     "Maupassant, “The Necklace”. Long periodic sentences split into clauses at B1.",
     "--target en --level B1"),
    ("de.en-B2.epub", "Deutsch → English · B2",
     "Kafka, The Metamorphosis. The B2 preset: one ¶ per sentence, fewer rubies (one per ~20 words).",
     "--target en --level B2"),
    ("es.en-C1.epub", "Español → English · C1, no translation",
     "Cervantes, Don Quixote. The C1 preset with translations off: two sentences per ¶, few rubies, "
     "notes on hard and archaic words only.",
     "--target en --level C1 --no-translation"),
]

TITLE = "glossbook sample"
CSS = """body { margin: 0 1em; line-height: 1.6; }
h1 { font-size: 1.5em; margin: 2em 0 0.5em; }
p { margin: 0 0 0.8em; }
code { font-size: 0.9em; }
.src { color: #666; font-size: 0.9em; }
"""


def page(title, body, lang="en"):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}"><head>'
            f'<title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="sample.css"/>'
            f'</head><body>{body}</body></html>\n')


def about():
    rows = "".join(f"<li>{html.escape(h)}</li>" for _, h, _, _ in PARTS)
    return page("About this sample", (
        "<h1>glossbook sample</h1>"
        "<p>Six short public-domain texts, each annotated by glossbook with different languages and "
        "settings (model: DeepSeek v4-pro). Tap a ¶ to open its note; the ¶ after a chapter title "
        "opens the chapter guide.</p>"
        f"<ol>{rows}</ol>"
        '<p class="src">Texts: Project Gutenberg (Dickens, Shakespeare, Frost, Kafka, Cervantes), '
        "Wikisource (Collodi, Maupassant), Aozora Bunko (Akutagawa). All in the public domain.</p>"))


def divider(i, head, what, cmd):
    return page(head, f"<h1>{i}. {html.escape(head)}</h1><p>{html.escape(what)}</p>"
                      f'<p class="src"><code>glossbook run BOOK.epub {html.escape(cmd)}</code></p>')


def read_book(path):
    z = zipfile.ZipFile(path)
    container = etree.fromstring(z.read("META-INF/container.xml"))
    opf_path = container.xpath("//*[local-name()='rootfile']/@full-path")[0]
    opf = etree.fromstring(z.read(opf_path))
    base = posixpath.dirname(opf_path)
    items = {it.get("id"): it for it in opf.find("o:manifest", NS)}
    nav_item = next(it for it in items.values() if "nav" in (it.get("properties") or "").split())
    nav = etree.fromstring(z.read(posixpath.join(base, nav_item.get("href"))))
    toc = [(a.xpath("string()").strip(), a.get("href"))
           for a in nav.xpath("//x:nav[@*[local-name()='type']='toc']//x:a", namespaces=NS)]
    langs = [e.text for e in opf.findall("o:metadata/dc:language", NS)]
    return z, base, opf, items, nav_item.get("id"), toc, langs


def main():
    files, manifest, spine, nav_lis, ncx_pts, langs = {}, [], [], [], [], []
    files["OEBPS/sample.css"] = CSS
    files["OEBPS/about.xhtml"] = about()
    manifest += ['<item id="sample-css" href="sample.css" media-type="text/css"/>',
                 '<item id="about" href="about.xhtml" media-type="application/xhtml+xml"/>']
    spine.append('<itemref idref="about"/>')
    nav_lis.append('<li><a href="about.xhtml">About this sample</a></li>')
    ncx_pts.append(("About this sample", "about.xhtml", []))
    for i, (name, head, what, cmd) in enumerate(PARTS, 1):
        z, base, opf, items, nav_id, toc, book_langs = read_book(BOOKS / name)
        langs += [lang for lang in book_langs if lang not in langs]
        d = f"b{i}"
        files[f"OEBPS/{d}.xhtml"] = divider(i, head, what, cmd)
        manifest.append(f'<item id="{d}" href="{d}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{d}"/>')
        for id_, it in items.items():
            if id_ == nav_id or it.get("media-type") == "application/x-dtbncx+xml":
                continue
            href = it.get("href")
            files[f"OEBPS/{d}/{href}"] = z.read(posixpath.join(base, href))
            props = f' properties="{it.get("properties")}"' if it.get("properties") else ""
            manifest.append(f'<item id="{d}-{id_}" href="{d}/{href}" media-type="{it.get("media-type")}"{props}/>')
        for ref in opf.find("o:spine", NS):
            if ref.get("idref") == nav_id:
                continue
            lin = ' linear="no"' if ref.get("linear") == "no" else ""
            spine.append(f'<itemref idref="{d}-{ref.get("idref")}"{lin}/>')
        sub = [(label, f"{d}/{href}") for label, href in toc]
        nav_lis.append(f'<li><a href="{d}.xhtml">{html.escape(head)}</a><ol>'
                       + "".join(f'<li><a href="{h}">{html.escape(t)}</a></li>' for t, h in sub) + "</ol></li>")
        ncx_pts.append((f"{i}. {head}", f"{d}.xhtml", sub))

    files["OEBPS/nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" '
        f'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en"><head><title>{TITLE}</title></head><body>'
        f'<nav epub:type="toc" id="toc"><ol>{"".join(nav_lis)}</ol></nav>'
        '<nav epub:type="landmarks" hidden=""><ol><li><a epub:type="bodymatter" href="about.xhtml">Start</a></li>'
        '</ol></nav></body></html>\n')
    n = 0
    pts = []
    for label, href, sub in ncx_pts:
        n += 1
        inner = ""
        for t, h in sub:
            n += 1
            inner += (f'<navPoint id="p{n}" playOrder="{n}"><navLabel><text>{html.escape(t)}</text></navLabel>'
                      f'<content src="{h}"/></navPoint>')
        pts.append(f'<navPoint id="p{n - len(sub)}" playOrder="{n - len(sub)}"><navLabel><text>{html.escape(label)}'
                   f'</text></navLabel><content src="{href}"/>{inner}</navPoint>')
    files["OEBPS/toc.ncx"] = ('<?xml version="1.0" encoding="utf-8"?>\n'
                              '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                              '<head><meta name="dtb:uid" content="urn:glossbook-sample"/></head>'
                              f'<docTitle><text>{TITLE}</text></docTitle><navMap>{"".join(pts)}</navMap></ncx>\n')
    manifest += ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                 '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>']
    lang_meta = "".join(f"<dc:language>{lang}</dc:language>" for lang in langs)
    files["OEBPS/content.opf"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="uid">urn:glossbook-sample</dc:identifier><dc:title>{TITLE}</dc:title>'
        f'<dc:creator>glossbook</dc:creator>{lang_meta}'
        '<meta property="dcterms:modified">2026-09-28T00:00:00Z</meta></metadata>'
        f'<manifest>{"".join(manifest)}</manifest><spine toc="ncx">{"".join(spine)}</spine>'
        '<guide><reference type="text" title="Start" href="about.xhtml"/></guide></package>\n')

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        for name, data in files.items():
            z.writestr(name, data)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
