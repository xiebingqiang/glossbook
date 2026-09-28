"""Real-world layouts: verse with one line per <p>, footnote markers, stanza numbers, bilingual books,
wrong dc:language, a TOC with a single entry."""
from conftest import FakeClient, make_epub
from test_e2e import check_epub, run_all

from glossbook import chapters, config, detect, options, pipeline, textnodes
from glossbook.epub import parse_xhtml

POEM = ("<h1>Song</h1><p>1</p>"
        "<p>Who rides so late through night and wind,</p><p>it is the father with his child;</p>"
        "<p>he holds the boy within his arm,</p><p>he clasps him tight, he keeps him warm.</p>"
        "<p>II</p>"
        "<p>My son, why hide your face in fear?</p><p>Father, do you not see the king,</p>"
        "<p>the elfking with his crown and tail?</p><p>My son, it is a streak of mist.</p>")


def _segs(path, per_note="2", lang="en"):
    book = chapters.open_book(path)
    s = config.resolve({"per_note": per_note}, from_file={})
    return book, pipeline.plan(book, book.chapters, s, lang)[1]


def test_verse_lines_are_joined(tmp_path):
    book, segs = _segs(make_epub(tmp_path / "p.epub", {"a.xhtml": POEM}))
    assert [len(sg.spans()) for sg in segs] == [5, 3]         # sentences 1 (4 lines) + 2; sentences 3 + 4
    assert segs[0].text.startswith("Who rides so late through night and wind, / it is the father")
    assert all(sg.text not in ("1", "II") for sg in segs)     # stanza numbers are skipped
    assert segs[0].block == segs[0].spans()[-1][0]            # the ¶ goes after the last line


def test_line_end_dash_stays_with_sentence():
    from glossbook import segment
    text = "Mein Sohn, es ist ein Nebelstreif. –\n«Du liebes Kind, komm. – Geh mit mir.»"
    assert [text[s:e] for s, e in segment.sentences(text, "de")] == \
        ["Mein Sohn, es ist ein Nebelstreif. –", "«Du liebes Kind, komm.", "– Geh mit mir.»"]


def test_prose_dialogue_is_not_verse(tmp_path):
    body = "".join(f"<p>“{w}.”</p>" for w in ("Yes", "No, not now", "Why not?", "Because I said so", "Fine"))
    _, segs = _segs(make_epub(tmp_path / "d.epub", {"a.xhtml": body}), per_note="3")
    assert all(len(sg.spans()) == 1 for sg in segs) and len(segs) == 5


def test_verse_end_to_end(tmp_path):
    out, outcome, _ = run_all(make_epub(tmp_path / "p.epub", {"a.xhtml": POEM}), tmp_path, FakeClient(),
                              per_note="2", density=1, intro=False)
    z, _ = check_epub(out)
    doc = z.read("OEBPS/Text/a.xhtml").decode()
    # one ¶ per segment (not per line); the first ¶ sits after the second sentence
    assert doc.count('class="gb-nr"') == 2
    assert doc.index("gb-nr") > doc.index("face in fear?")
    assert "<ruby" in doc.split("keeps him warm")[0]                  # rubies can be in earlier lines


def test_noteref_markers_left_out():
    root = parse_xhtml(b'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                       b'<p>Toschi,<span class="apice">4</span> e i regni<sup>[2]</sup> crudi'
                       b'<a href="n.xhtml#f3">3</a>; anni <span>1492</span> e <b>5</b> gatti</p></body></html>').getroot()
    p = root[0][0]
    _, text = textnodes.collect(p)
    assert text == "Toschi, e i regni crudi; anni 1492 e 5 gatti"


def test_page_numbers_left_out():
    root = parse_xhtml(b'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>'
                       b'<p>auf diese <span class="origpage" id="origpage_12">[12]</span>Erscheinung.'
                       b'<span epub:type="pagebreak" id="p13" title="13"/> Seite <span id="page-xiv">xiv</span>'
                       b' und <span class="pagename">Kapitel</span> <span class="page">12 Monate</span></p>'
                       b'</body></html>').getroot()
    _, text = textnodes.collect(root[0][0])
    assert text == "auf diese Erscheinung. Seite  und Kapitel 12 Monate"


def test_foreign_script_blocks_skipped(tmp_path):
    body = "<p>Je ne sais jamais bien jusqu’où remonter.</p><p>我老是搞不清该从哪儿说起。</p><p>序幕</p>"
    _, segs = _segs(make_epub(tmp_path / "b.epub", {"a.xhtml": body}, lang="fr"), lang="fr")
    assert [sg.text for sg in segs] == ["Je ne sais jamais bien jusqu’où remonter."]
    assert detect.foreign("OK", "zh") and not detect.foreign("ciao 你好世界朋友", "zh")


def test_language_detection(tmp_path, capsys):
    fr = "<p>" + " ".join(["Elle ne savait pas que le jardin était dans la maison avec les fleurs."] * 30) + "</p>"
    book = chapters.open_book(make_epub(tmp_path / "f.epub", {"a.xhtml": fr}, lang="en"))
    s = config.resolve({}, from_file={})
    assert options.source_lang(book, s) == "fr"
    assert "dc:language says 'en'" in capsys.readouterr().err
    s = config.resolve({"source": "en"}, from_file={})
    assert options.source_lang(book, s) == "en"                   # --source always wins
    assert detect.guess("短" * 300) == ("zh", 1.0)
    assert detect.guess("かなとカナ" * 60)[0] == "ja"


def test_single_entry_toc_falls_back_to_files(tmp_path):
    docs = {f"c{i}.xhtml": f"<p>{i}.</p><p>" + "Some words here. " * 400 + "</p>" for i in range(1, 5)}
    b = chapters.open_book(make_epub(tmp_path / "t.epub", docs, toc=[("Start", "c1.xhtml")]))
    assert [c.title for c in b.chapters] == ["1.", "2.", "3.", "4."]

