"""Reading EPUBs: TOC layouts, DRM, entities, broken files."""
import pytest
from conftest import make_epub

from glossbook import chapters, epub


def test_epub3_nav_chapters(simple_book):
    b = chapters.open_book(simple_book)
    assert b.lang == "en" and b.version == "3.0"
    assert [c.title for c in b.chapters] == ["Chapter 1", "Chapter 2"]
    assert [c.index for c in b.chapters] == [1, 2]
    assert b.chapters[0].words > 20


def test_epub2_ncx_only(tmp_path):
    p = make_epub(tmp_path / "b.epub", {"a.xhtml": "<p>Hello world.</p>"}, version="2.0", nav=False)
    b = chapters.open_book(p)
    assert b.nav_path is None and len(b.chapters) == 1 and b.chapters[0].title == "Chapter 1"


def test_multiple_chapters_in_one_file_with_anchors(tmp_path):
    body = ('<h2 id="c1">One</h2><p>First text here.</p><p>More first.</p>'
            '<h2 id="c2">Two</h2><p>Second text.</p><div><span id="c3"/>Third text.</div>')
    p = make_epub(tmp_path / "b.epub", {"all.xhtml": body},
                  toc=[("One", "all.xhtml#c1"), ("Two", "all.xhtml#c2"), ("Three", "all.xhtml#c3")])
    b = chapters.open_book(p)
    assert [(c.title, c.end - c.start) for c in b.chapters] == [("One", 3), ("Two", 2), ("Three", 1)]


def test_chapter_spanning_files_and_front_matter(tmp_path):
    p = make_epub(tmp_path / "b.epub",
                  {"front.xhtml": "<p>Copyright notice text.</p>", "c1a.xhtml": "<p>Part A.</p>",
                   "c1b.xhtml": "<p>Part B.</p>", "c2.xhtml": "<p>Next.</p>"},
                  toc=[("Ch 1", "c1a.xhtml"), ("Ch 2", "c2.xhtml")])
    b = chapters.open_book(p)
    assert [c.index for c in b.chapters] == [0, 1, 2]
    assert b.chapters[0].title == "(front matter)"
    assert b.chapters[1].end - b.chapters[1].start == 2


def test_no_toc_falls_back_to_files(tmp_path):
    p = make_epub(tmp_path / "b.epub", {"a.xhtml": "<h1>Alpha</h1><p>x y.</p>", "b.xhtml": "<p>z w.</p>"},
                  toc=[], ncx=False, nav=False)
    b = chapters.open_book(p)
    assert [c.title for c in b.chapters] == ["Alpha", "b.xhtml"]


def test_nonlinear_and_nested_blocks(tmp_path):
    p = make_epub(tmp_path / "b.epub",
                  {"a.xhtml": "<div><p>In div.</p><blockquote><p>Quoted.</p></blockquote></div>"
                              "<table><tr><td>cell</td></tr></table><ul><li>Item one.</li></ul>",
                   "note.xhtml": "<p>Endnote.</p>"},
                  linear={"note.xhtml": False})
    b = chapters.open_book(p)
    assert [bl.text for bl in b.blocks] == ["In div.", "Quoted.", "Item one."]


def test_html_entities_and_broken_xhtml(tmp_path):
    raw = ('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body>'
           '<p>A&nbsp;b &mdash; c &amp; d.</p><p>Unclosed <b>bold</p></body></html>')
    p = make_epub(tmp_path / "b.epub", {"a.xhtml": ""}, raw_docs={"a.xhtml": raw})
    b = chapters.open_book(p)
    assert b.blocks[0].text == "A b — c & d."
    assert len(b.blocks) == 2


def test_drm_detection(tmp_path):
    p = make_epub(tmp_path / "a.epub", {"a.xhtml": "<p>x.</p>"}, extra={"META-INF/rights.xml": "<r/>"})
    with pytest.raises(epub.EpubError, match="DRM"):
        epub.load(p)
    enc = ('<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
           'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
           '<enc:EncryptionMethod Algorithm="{}"/></enc:EncryptedData></encryption>')
    p2 = make_epub(tmp_path / "b.epub", {"a.xhtml": "<p>x.</p>"},
                   extra={"META-INF/encryption.xml": enc.format("http://www.w3.org/2001/04/xmlenc#aes128-cbc")})
    with pytest.raises(epub.EpubError):
        epub.load(p2)
    p3 = make_epub(tmp_path / "c.epub", {"a.xhtml": "<p>x.</p>"},
                   extra={"META-INF/encryption.xml": enc.format("http://www.idpf.org/2008/embedding")})
    assert epub.load(p3).blocks


def test_not_a_zip(tmp_path):
    p = tmp_path / "x.epub"
    p.write_text("nope")
    with pytest.raises(epub.EpubError):
        epub.load(p)


def test_select_chapters(simple_book):
    b = chapters.open_book(simple_book)
    assert [c.index for c in chapters.select(b, "2")] == [2]
    assert [c.index for c in chapters.select(b, "1-")] == [1, 2]
    assert len(chapters.select(b, None)) == 2
    with pytest.raises(ValueError):
        chapters.select(b, "7-9")
    with pytest.raises(ValueError):
        chapters.select(b, "abc")


def test_broken_toc_falls_back(tmp_path):
    """A TOC whose only entry is the license at the end (common in Gutenberg plain-text
    conversions) -> one chapter per file."""
    long = "<p>" + "Lorem ipsum dolor sit amet. " * 60 + "</p>"
    p = make_epub(tmp_path / "b.epub", {"a.xhtml": long, "b.xhtml": long, "c.xhtml": long, "lic.xhtml": "<p>License.</p>"},
                  toc=[("LICENSE", "lic.xhtml")])
    b = chapters.open_book(p)
    assert len(b.chapters) == 4 and b.chapters[0].index == 1


def test_gutenberg_license_not_selected_by_default(tmp_path):
    long = "<p>" + "Lorem ipsum dolor sit amet. " * 60 + "</p>"
    p = make_epub(tmp_path / "g.epub", {"a.xhtml": long, "lic.xhtml": long},
                  toc=[("Chapter 1", "a.xhtml"), ("THE FULL PROJECT GUTENBERG™ LICENSE", "lic.xhtml")])
    b = chapters.open_book(p)
    assert [c.title for c in chapters.select(b, None)] == ["Chapter 1"]
    assert len(chapters.select(b, "1-2")) == 2
