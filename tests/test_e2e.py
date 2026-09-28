"""End to end with a fake model: output EPUB structure, cache, retries, cost limit, build, CLI."""
import io
import re
import zipfile

import pytest
from conftest import FakeClient, make_epub
from lxml import etree

from glossbook import chapters, cli, config, package, pipeline, placement, preview, render

OPF = "{http://www.idpf.org/2007/opf}"


def run_all(path, tmp_path, client, **kw):
    spec = kw.pop("chapters", None)
    s = config.resolve({"model": "fake", **kw}, from_file={})
    book = chapters.open_book(path)
    lang = s.source or book.lang
    chosen = chapters.select(book, spec)
    work = pipeline.Work(tmp_path / "work")
    outcome, plans = pipeline.run(book, chosen, s, lang, work, client, progress=lambda *_: None)
    placed = placement.choose(book, plans, outcome.results, s, lang)
    notes = render.apply(book, chosen, plans, outcome, placed, s)
    out = tmp_path / "out.epub"
    first = book.blocks[chosen[0].start].doc
    package.write(book, out, notes, s, first)
    return out, outcome, work


def check_epub(out):
    """mimetype first and stored; every XHTML parses; both ends of every ¶ and ↩ link exist."""
    z = zipfile.ZipFile(out)
    first = z.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    names = set(z.namelist())
    assert len(names) == len(z.namelist())            # no duplicate entries
    ids, links = {}, []
    for n in names:
        if n.endswith(".xhtml"):
            root = etree.fromstring(z.read(n))
            ids[n] = {e.get("id") for e in root.iter() if e.get("id")}
            for a in root.iter("{http://www.w3.org/1999/xhtml}a"):
                h = a.get("href", "")
                if "#" in h and not h.startswith("http"):
                    f, frag = h.split("#")
                    links.append((n, f, frag))
    for src, f, frag in links:
        target = src if not f else re.sub(r"[^/]+$", f, src)
        if target in ids and (frag.startswith("n-") or frag.startswith("r-")):
            assert frag in ids[target], (src, f, frag)
    opf = etree.fromstring(z.read("OEBPS/content.opf"))
    assert opf.get("version") == "3.0"
    return z, opf


def test_full_run_structure(simple_book, tmp_path):
    fake = FakeClient()
    out, outcome, _ = run_all(simple_book, tmp_path, fake)
    z, opf = check_epub(out)
    c1 = z.read("OEBPS/Text/c1.xhtml").decode()
    assert c1.count("gb-nr") >= 4 and "<rt>" in c1 and 'epub:type="noteref"' in c1
    assert "gb-style.css" in c1 and "<!DOCTYPE" in c1
    notes = z.read("OEBPS/Text/gb-notes-c1.xhtml").decode()
    assert "T: It was a dark and stormy night." in notes and "Summary" in notes
    assert "notinthetext" not in notes                 # guide keywords not in the text are dropped
    spine = [(i.get("idref"), i.get("linear")) for i in opf.iter(f"{OPF}itemref")]
    assert ("gb-notes-0", "no") in spine
    assert "(annotated)" in z.read("OEBPS/content.opf").decode()
    c2 = z.read("OEBPS/Text/c2.xhtml").decode()
    assert re.search(r"</a>\s*<a class=\"gb-nr\"", c2) or "labyrinthine</a>" in c2   # words inside links get no ruby


def test_cache_second_run_no_calls(simple_book, tmp_path):
    fake = FakeClient()
    run_all(simple_book, tmp_path, fake)
    n = len(fake.calls)
    fake2 = FakeClient()
    run_all(simple_book, tmp_path, fake2)
    assert n > 0 and fake2.calls == []


def test_missing_segments_retried_and_bad_words_dropped(simple_book, tmp_path):
    fake = FakeClient(drop={1}, bad_word=True)
    _, outcome, _ = run_all(simple_book, tmp_path, fake, intro=False)
    retries = [c for c in fake.calls if c[1]]
    assert retries and "[0]" in retries[0][2] and "[1]" not in retries[0][2]   # only the missing segment is re-sent
    assert outcome.stats["dropped"] > 0 and outcome.stats["missing"] == 0
    assert all(r.tr for r in outcome.results.values())
    assert not any(g.w == "zzzqqq" for r in outcome.results.values() for g in r.gl)


def test_budget_stops(simple_book, tmp_path):
    fake = FakeClient()
    _, outcome, _ = run_all(simple_book, tmp_path, fake, max_cost=0.0000001, jobs=1, intro=False)
    assert outcome.stats["skipped_budget"] >= 1


def test_chinese_source_and_target(tmp_path):
    p = make_epub(tmp_path / "zh.epub", {"a.xhtml": "<h1>第一章</h1><p>那天晚上他很晚才回到家里，屋子里一片漆黑。她已经走了，桌上留着一封没有署名的信。</p>"}, lang="zh-CN")
    out, outcome, _ = run_all(p, tmp_path, FakeClient(target="en"), target="en")
    z, _ = check_epub(out)
    assert z.read("OEBPS/Text/a.xhtml").decode().count("gb-nr") >= 2


def test_epub2_upgraded_with_nav_and_guide(tmp_path):
    p = make_epub(tmp_path / "b.epub", {"a.xhtml": "<p>Hello there, general Kenobi.</p>"}, version="2.0", nav=False)
    out, _, _ = run_all(p, tmp_path, FakeClient(), intro=False)
    z, opf = check_epub(out)
    nav = z.read("OEBPS/gb-nav.xhtml").decode()
    assert 'epub:type="toc"' in nav and 'epub:type="bodymatter"' in nav
    assert any(r.get("type") == "text" for r in opf.iter(f"{OPF}reference"))
    assert any(i.get("properties") == "nav" for i in opf.iter(f"{OPF}item"))


def test_only_selected_chapters_modified(simple_book, tmp_path):
    out, _, _ = run_all(simple_book, tmp_path, FakeClient(), chapters="2")
    z = zipfile.ZipFile(out)
    assert "gb-nr" not in z.read("OEBPS/Text/c1.xhtml").decode()
    assert "gb-nr" in z.read("OEBPS/Text/c2.xhtml").decode()


def test_preview_html(simple_book, tmp_path):
    s = config.resolve({"model": "fake"}, from_file={})
    book = chapters.open_book(simple_book)
    work = pipeline.Work(tmp_path / "w")
    outcome, plans = pipeline.run(book, book.chapters[:1], s, "en", work, FakeClient(), progress=lambda *_: None)
    h = preview.build(book, book.chapters[:1], plans, outcome, s, "en", [("a", "b")], "T")
    assert h.count('class="variant"') == 4 * 3      # B1..C2 x three densities
    assert "T: It was a dark" in h and "<rt>" in h


# ---------- CLI ----------

@pytest.fixture
def patched_cli(monkeypatch):
    fakes = []

    def fake_client(s, work):
        s.model = "ds4pro"
        f = FakeClient()
        f.log.path = work.usage
        fakes.append(f)
        return f, {"name": "ds4pro", "price": {"input": 1, "output": 2}}
    monkeypatch.setattr(cli, "_client", fake_client)
    monkeypatch.chdir(pytest.importorskip("pathlib").Path(__file__).parent)
    return fakes


def test_cli_run_build_report(simple_book, tmp_path, patched_cli, capsys):
    out = tmp_path / "o.epub"
    cli.main(["run", str(simple_book), "--yes", "-o", str(out), "--target", "zh"])
    assert out.exists()
    n_calls = len(patched_cli[0].calls)
    out2 = tmp_path / "o2.epub"
    cli.main(["build", str(simple_book), "--level", "C1", "--density", "low", "-o", str(out2)])
    assert out2.exists() and len(patched_cli) == 1 and n_calls > 0
    cli.main(["report", str(simple_book)])
    assert "Total:" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["build", str(simple_book), "--target", "fr"])


def test_cli_run_remembers_settings(simple_book, tmp_path, patched_cli, capsys):
    cli.main(["preview", str(simple_book), "--words", "20", "--target", "zh", "-o", str(tmp_path / "p.html")])
    cli.main(["run", str(simple_book), "--yes", "-o", str(tmp_path / "o.epub")])
    assert "target=zh" in capsys.readouterr().out
    state = pipeline.Work(simple_book.with_suffix(".glossbook")).state()
    assert state["gen"]["target"] == "zh" and state["settings"] == {"target": "zh"}


def test_cli_run_needs_yes_without_terminal(simple_book, patched_cli, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit, match="--yes"):
        cli.main(["run", str(simple_book)])
    assert not patched_cli[0].calls


def test_fatal_error_stops_sending(simple_book, tmp_path):
    from glossbook.llm import LLMError

    class Broken(FakeClient):
        def chat(self, *a, **kw):
            super().chat(*a, **kw)
            raise LLMError("key rejected")
    broken = Broken()
    with pytest.raises(LLMError):
        run_all(simple_book, tmp_path, broken, jobs=1, chunk_words=5, intro=False)
    assert len(broken.calls) == 1


def test_cli_preview(simple_book, tmp_path, patched_cli, capsys):
    cli.main(["preview", str(simple_book), "--words", "20", "-o", str(tmp_path / "p.html")])
    assert (tmp_path / "p.html").exists() and "All selected chapters" in capsys.readouterr().out


def test_cli_rejects_rtl(tmp_path, patched_cli):
    p = make_epub(tmp_path / "ar.epub", {"a.xhtml": "<p>مرحبا بالعالم.</p>"}, lang="ar")
    with pytest.raises(SystemExit, match="right-to-left"):
        cli.main(["run", str(p), "--yes"])
    p2 = make_epub(tmp_path / "en.epub", {"a.xhtml": "<p>Hi.</p>"})
    with pytest.raises(SystemExit, match="right-to-left"):
        cli.main(["inspect", str(p2), "--target", "he"])


# ---------- more edge cases ----------

def test_epub2_upgrade_normalizes_untouched_docs(tmp_path):
    raw = ('<?xml version="1.0"?><!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "x.dtd">'
           '<html xmlns="http://www.w3.org/1999/xhtml"><head><title></title></head>'
           '<body><p>Front&nbsp;page &copy; 2003.</p></body></html>')
    p = make_epub(tmp_path / "b.epub", {"front.xhtml": "", "a.xhtml": "<p>Hello there, general Kenobi. How are you today?</p>"},
                  version="2.0", nav=False, raw_docs={"front.xhtml": raw}, toc=[("A", "a.xhtml")])
    out, _, _ = run_all(p, tmp_path, FakeClient(), intro=False, chapters="1")
    z = zipfile.ZipFile(out)
    front = z.read("OEBPS/Text/front.xhtml").decode()
    assert "&nbsp;" not in front and "<!DOCTYPE html>" in front and "<title>Test Book</title>" in front
    etree.fromstring(front.encode())                   # undeclared entities were replaced, so it parses
    a = z.read("OEBPS/Text/a.xhtml").decode()
    assert "<!DOCTYPE html>" in a
    opf = z.read("OEBPS/content.opf").decode()
    uid = re.search(r'<dc:identifier id="uid">([^<]+)<', opf).group(1)
    assert uid != "urn:test"
    assert f'content="{uid}"' in z.read("OEBPS/toc.ncx").decode() or 'name="dtb:uid"' not in z.read("OEBPS/toc.ncx").decode()


def test_existing_ruby_br_and_footnote_links(tmp_path):
    body = ('<p>吾輩は<ruby>猫<rt>ねこ</rt></ruby>である。名前はまだ無い。<br/>どこで生れたか頓と見当がつかぬ。'
            '<a href="n.xhtml#f1" epub:type="noteref">1</a></p>')
    p = make_epub(tmp_path / "ja.epub", {"a.xhtml": body}, lang="ja")
    b = chapters.open_book(p)
    assert "ねこ" not in b.blocks[0].text and "\n" in b.blocks[0].text
    out, outcome, _ = run_all(p, tmp_path, FakeClient(), intro=False)
    z, _ = check_epub(out)
    a = z.read("OEBPS/Text/a.xhtml").decode()
    root = etree.fromstring(a.encode())
    rubies = list(root.iter("{http://www.w3.org/1999/xhtml}ruby"))
    assert all(r.find("{http://www.w3.org/1999/xhtml}ruby") is None for r in rubies)   # no ruby inside ruby
    links = list(root.iter("{http://www.w3.org/1999/xhtml}a"))
    assert all(a.find("{http://www.w3.org/1999/xhtml}a") is None for a in links)        # no link inside a link
    assert "<rt>ねこ</rt>" in a


def test_per_note_para_one_marker_per_paragraph(simple_book, tmp_path):
    out, _, _ = run_all(simple_book, tmp_path, FakeClient(), per_note="para", intro=False, chapters="1")
    c1 = zipfile.ZipFile(out).read("OEBPS/Text/c1.xhtml").decode()
    assert c1.count('class="gb-nr"') == 3               # 3 paragraphs, one ¶ each


def test_warmup_request_goes_first(simple_book, tmp_path):
    fake = FakeClient()
    run_all(simple_book, tmp_path, fake, jobs=4)
    assert fake.calls[0][0] == "seg"                    # a segment request goes first (warms the cache)


def test_culture_note_rendered(simple_book, tmp_path):
    class CultureClient(FakeClient):
        def chat(self, messages, kind="seg", chapter=None, retry=False):
            out = super().chat(messages, kind, chapter, retry)
            return out if kind == "intro" else out.replace("\n- ", "\n* An allusion.\n- ", 1)
    out, _, _ = run_all(simple_book, tmp_path, CultureClient(), intro=False)
    notes = zipfile.ZipFile(out).read("OEBPS/Text/gb-notes-c1.xhtml").decode()
    assert "An allusion." in notes and 'class="gb-cu"' in notes
    out2, _, _ = run_all(simple_book, tmp_path / "x", CultureClient(), intro=False, culture=False)
    assert "An allusion." not in zipfile.ZipFile(out2).read("OEBPS/Text/gb-notes-c1.xhtml").decode()


def test_note_pages_split_by_size(simple_book, tmp_path, monkeypatch):
    monkeypatch.setattr(render, "NOTES_MAX_BYTES", 300)
    out, _, _ = run_all(simple_book, tmp_path, FakeClient())
    z, opf = check_epub(out)
    pages = [n for n in z.namelist() if "gb-notes-c1" in n]
    assert len(pages) > 1 and "OEBPS/Text/gb-notes-c1-2.xhtml" in pages
    spine = [i.get("idref") for i in opf.iter(f"{OPF}itemref")]
    assert "gb-notes-0" in spine and "gb-notes-0-1" in spine
