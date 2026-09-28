"""Test helpers: build EPUBs on the fly (EPUB2/3, various TOC layouts) and an offline fake model client."""
import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glossbook import usage  # noqa: E402

XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head><body>{body}</body></html>"""


def make_epub(path, docs, lang="en", version="3.0", toc=None, ncx=True, nav=True, extra=None,
              linear=None, raw_docs=None):
    """docs: {file name: body HTML} in spine order; toc: [(title, href)], default one entry per file."""
    toc = toc if toc is not None else [(f"Chapter {i + 1}", n) for i, n in enumerate(docs)]
    linear = linear or {}
    items, spine = [], []
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        for i, (name, body) in enumerate(docs.items()):
            content = (raw_docs or {}).get(name) or XHTML.format(body=body)
            z.writestr(f"OEBPS/Text/{name}", content)
            items.append(f'<item id="d{i}" href="Text/{name}" media-type="application/xhtml+xml"/>')
            lin = ' linear="no"' if linear.get(name) is False else ""
            spine.append(f'<itemref idref="d{i}"{lin}/>')
        if nav and version.startswith("3"):
            lis = "".join(f'<li><a href="Text/{h}">{t}</a></li>' for t, h in toc)
            z.writestr("OEBPS/nav.xhtml",
                       '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                       'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>n</title></head><body>'
                       f'<nav epub:type="toc"><ol>{lis}</ol></nav></body></html>')
            items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        if ncx:
            pts = "".join(f'<navPoint id="n{i}" playOrder="{i + 1}"><navLabel><text>{t}</text></navLabel>'
                          f'<content src="Text/{h}"/></navPoint>' for i, (t, h) in enumerate(toc))
            z.writestr("OEBPS/toc.ncx", '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
                       f'version="2005-1"><navMap>{pts}</navMap></ncx>')
            items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        for name, data in (extra or {}).items():
            z.writestr(name, data)
        spine_attr = ' toc="ncx"' if ncx else ""
        z.writestr("OEBPS/content.opf",
                   f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" '
                   f'version="{version}" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   f'<dc:identifier id="uid">urn:test</dc:identifier><dc:title>Test Book</dc:title>'
                   f'<dc:language>{lang}</dc:language></metadata><manifest>{"".join(items)}</manifest>'
                   f'<spine{spine_attr}>{"".join(spine)}</spine></package>')
    return path


class FakeResp:
    pass


class FakeClient:
    """Answers every [n] segment of the request: translation = "T: " + text; glosses the longest word (C1).
    drop: segment numbers left out of the first answer; bad_word: add an expression not in the text."""

    def __init__(self, target="en", drop=(), bad_word=False, price=None, cost_per_call=0.0):
        self.log = usage.UsageLog(None, price or {"input": 1, "output": 2})
        self.calls = []
        self.drop = set(drop)
        self.bad_word = bad_word
        self.target = target

    def chat(self, messages, kind="seg", chapter=None, retry=False):
        user = messages[-1]["content"]
        self.calls.append((kind, retry, user))
        self.log.add("fake", kind, chapter, {"prompt": len(user) // 3 + 500, "cached": 400,
                                             "completion": 100, "reasoning": 0}, retry)
        if kind == "intro":
            word = max(re.findall(r"\w+", user.split("\n\n", 1)[1]), key=len)
            return f"S: A summary.\nP: Someone — a person\nK: {word} | kw gloss\nK: notinthetext | nope"
        out = []
        for m in re.finditer(r"^\[(\d+)\] (.*)$", user, re.M):
            n, text = int(m.group(1)), m.group(2)
            if n in self.drop and not retry:
                continue
            out.append(f"[{n}] T: {text}")
            words = re.findall(r"\w[\w’']*", text)
            if words:
                w = max(words, key=len)
                out.append(f"- {w} | gl-{w[:4]} | C1 | note | ")
            if self.bad_word:
                out.append("- zzzqqq | missing | C2 | |")
        return "\n".join(out)


@pytest.fixture
def fake():
    return FakeClient()


@pytest.fixture
def simple_book(tmp_path):
    body1 = ("<h1>One</h1><p>It was a <em>dark and stormy</em> night. The rain fell in torrents, except at "
             "occasional intervals, when it was checked by a violent gust of wind.</p>"
             "<p>Mr. Smith said: “Hello there.” Then he left.</p>"
             "<p>Nobody in the village could remember a winter so bitter, and the old men gathered by the fire "
             "to argue about whether the river would freeze before the feast of Saint Martin.</p>")
    body2 = "<h2>Two</h2><p>She wandered through the <a href='x.xhtml'>labyrinthine</a> corridors.</p>"
    return make_epub(tmp_path / "book.epub", {"c1.xhtml": body1, "c2.xhtml": body2})
