"""Build the small public-domain source EPUBs for the demo sample (one per source language).

Texts come from samples/src/ (Project Gutenberg, Wikisource, Aozora Bunko); see README in this folder.
Usage: python3 samples/make_sources.py   -> samples/books/*.epub
"""
import html
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
OUT = HERE / "books"


def paras(text):
    """Blank-line separated paragraphs, lines joined."""
    text = text.replace("\r\n", "\n")
    return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]


def between(path, start, end, enc="utf-8"):
    t = (SRC / path).read_text(encoding=enc).replace("\r\n", "\n")
    i = t.index(start)
    return t[i:t.index(end, i)]


def p(t, cls=None):
    c = f' class="{cls}"' if cls else ""
    return f"<p{c}>{html.escape(t, quote=False)}</p>"


def verse(lines_text):
    """Stanzas separated by blank lines; one <p> per line (glossbook joins them into sentences)."""
    out = []
    for stanza in re.split(r"\n\s*\n", lines_text.strip("\n")):
        lines = [ln.strip().strip("_") for ln in stanza.splitlines() if ln.strip()]
        out.append('<div class="stanza">' + "".join(p(ln, "line") for ln in lines) + "</div>")
    return "".join(out)


# ---- texts ---------------------------------------------------------------------------------------

def carol():
    end = "literally to astonish"
    body = paras(between("pg46.txt", "MARLEY was dead", end) + end + " his son's weak mind.")
    body[0] = body[0].replace("MARLEY", "Marley", 1)
    return "Stave I: Marley's Ghost", "".join(p(x) for x in body)


def poems():
    son = between("pg1041.txt", "Shall I compare thee", "\n\nXIX")
    road = between("pg29345.txt", "  _Two roads diverged in a yellow", "all the difference._") + "all the difference._"
    return "Two Poems", ("<h2>Sonnet 18 — William Shakespeare</h2>" + verse(son)
                         + "<h2>The Road Not Taken — Robert Frost</h2>" + verse(road))


def kumo():
    t = (SRC / "kumono_ito.txt").read_bytes().decode("cp932")
    t = t.replace("\r\n", "\n")
    t = t[t.index("［＃８字下げ］一"):t.index("［＃地から")]
    t = re.sub(r"※［＃「特のへん＋廴＋聿」[^］]*］", "犍", t)
    t = re.sub(r"《[^》]*》", "", t).replace("｜", "")
    out = []
    for line in t.splitlines():
        m = re.match(r"［＃８字下げ］(.)［＃", line)
        if m:
            out.append(f"<h2>{m.group(1)}</h2>")
        elif line.strip():
            out.append(p(re.sub(r"［＃[^］]*］", "", line).strip()))
    return "蜘蛛の糸", "".join(out)


def pinocchio():
    ps = paras((SRC / "pinocchio.txt").read_text())
    ps = [x.replace(".... sentì una vocina sottile sottile. ", "") for x in ps]
    sub = ps[1]
    return "Capitolo I", p(sub, "sub") + "".join(p(x) for x in ps[2:14])


def parure():
    return "La Parure", "".join(p(x) for x in paras((SRC / "parure.txt").read_text())[:4])


def kafka():
    body = paras(between("pg22367.txt", "Als Gregor Samsa", "\n\n»Ach Gott,«"))
    return "Die Verwandlung — I", "".join(p(x) for x in body)


def quijote():
    body = paras(between("pg2000.txt", "En un lugar de la Mancha", "\n\nEs, pues, de saber"))
    return "Capítulo primero", p("Que trata de la condición y ejercicio del famoso hidalgo don Quijote de la Mancha",
                                 "sub") + "".join(p(x) for x in body)


# name, language, title, author, chapters
BOOKS = [
    ("en", "en", "English Classics", "Charles Dickens; William Shakespeare; Robert Frost", [carol, poems]),
    ("ja", "ja", "蜘蛛の糸", "芥川龍之介", [kumo]),
    ("it", "it", "Le avventure di Pinocchio", "Carlo Collodi", [pinocchio]),
    ("fr", "fr", "La Parure", "Guy de Maupassant", [parure]),
    ("de", "de", "Die Verwandlung", "Franz Kafka", [kafka]),
    ("es", "es", "Don Quijote de la Mancha", "Miguel de Cervantes", [quijote]),
]

CONTAINER = ('<?xml version="1.0"?><container version="1.0" '
             'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
             '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
             '</rootfiles></container>')

CSS = """body { margin: 0 1em; line-height: 1.6; }
h1 { font-size: 1.4em; margin: 1em 0; }
h2 { font-size: 1.1em; margin: 1.2em 0 0.6em; }
p { margin: 0; text-indent: 1.5em; }
p.sub { font-style: italic; text-indent: 0; margin-bottom: 1em; }
div.stanza { margin: 0 0 1em 1em; }
p.line { text-indent: 0; }
"""


def xhtml(lang, title, body):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}"><head>'
            f'<title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>'
            f'<body><h1>{html.escape(title)}</h1>{body}</body></html>\n')


def write(name, lang, title, author, chapters):
    path = OUT / f"{name}.epub"
    docs = [f() for f in chapters]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/style.css", CSS)
        items, spine, lis = [], [], []
        for i, (t, body) in enumerate(docs, 1):
            z.writestr(f"OEBPS/ch{i}.xhtml", xhtml(lang, t, body))
            items.append(f'<item id="ch{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="ch{i}"/>')
            lis.append(f'<li><a href="ch{i}.xhtml">{html.escape(t)}</a></li>')
        z.writestr("OEBPS/nav.xhtml",
                   '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
                   '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
                   f'xml:lang="{lang}"><head><title>{html.escape(title)}</title></head>'
                   f'<body><nav epub:type="toc" id="toc"><ol>{"".join(lis)}</ol></nav></body></html>\n')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0" encoding="utf-8"?>\n'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:identifier id="uid">urn:glossbook-sample:{name}</dc:identifier>'
                   f'<dc:title>{html.escape(title)}</dc:title><dc:creator>{html.escape(author)}</dc:creator>'
                   f'<dc:language>{lang}</dc:language>'
                   '<meta property="dcterms:modified">2026-09-28T00:00:00Z</meta></metadata><manifest>'
                   '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
                   '<item id="css" href="style.css" media-type="text/css"/>'
                   f'{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>\n')
    return path


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for b in BOOKS:
        print(write(*b))
