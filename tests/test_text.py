"""Sentence splitting, finding expressions, text-node insertion."""
from lxml import etree

from glossbook import match, segment, textnodes


def spans_text(text, spans):
    return [text[s:e] for s, e in spans]


# ---------- sentences ----------

def test_english_abbrev_and_quotes():
    t = 'Mr. Smith met Dr. Jones. “Where are you going?” he asked. J. K. Rowling agreed.'
    assert spans_text(t, segment.sentences(t, "en")) == [
        "Mr. Smith met Dr. Jones.", "“Where are you going?” he asked.", "J. K. Rowling agreed."]


def test_lowercase_after_period_not_split():
    t = "Il sig. rossi arrivò... e poi se ne andò."
    assert len(segment.sentences(t, "it")) == 1


def test_italian_guillemets_and_ellipsis():
    t = "«Vieni qui!» gridò. Nessuno rispose… Poi tornò il silenzio."
    assert spans_text(t, segment.sentences(t, "it")) == ["«Vieni qui!» gridò.", "Nessuno rispose…", "Poi tornò il silenzio."]


def test_spanish_inverted_marks():
    t = "Hola. ¿Cómo estás? ¡Muy bien!"
    assert len(segment.sentences(t, "es")) == 3


def test_chinese_and_japanese():
    t = "他来了。“你好！”她说。然后呢？"
    assert spans_text(t, segment.sentences(t, "zh")) == ["他来了。", "“你好！”", "她说。", "然后呢？"]
    j = "吾輩は猫である。名前はまだ無い。「どこで生れたか」とんと見当がつかぬ。"
    assert len(segment.sentences(j, "ja")) == 3


def test_korean_caseless():
    t = "나는 학생이다. 그는 선생님이다."
    assert len(segment.sentences(t, "ko")) == 2


def test_german_nouns_capitalized_still_fine():
    t = "Er kam z.B. am Montag. Das Haus war leer."
    assert spans_text(t, segment.sentences(t, "de")) == ["Er kam z.B. am Montag.", "Das Haus war leer."]


def test_clause_split_long_sentence():
    t = ("La gente diffida degli scapoli in vacanza, soprattutto se di una certa età: li considerano "
         "persone molto egoiste, e forse un po' viziose; non hanno torto, del resto, e lo sanno tutti bene.")
    segs = segment.segments(t, "it", "clause", 12)
    assert len(segs) >= 3
    assert all(segment.units(t[s:e], "it") <= 12 for s, e in segs)
    assert "".join(t[s:e] for s, e in segs).replace(" ", "") == t.replace(" ", "")


def test_unsplittable_long_sentence_kept():
    t = " ".join(["parola"] * 40) + "."
    assert segment.segments(t, "it", "clause", 25) == [(0, len(t))]


def test_short_sentences_merged_and_grouping():
    t = "Sì. Va bene. Allora andiamo a casa adesso, perché è tardi e piove forte."
    assert spans_text(t, segment.segments(t, "it", "clause", 25))[0] == "Sì. Va bene."
    t2 = "A b c. D e f. G h i. J k l. M n o."
    assert len(segment.segments(t2, "en", "2")) == 3
    assert segment.segments(t2, "en", "para") == [(0, len(t2))]
    assert len(segment.segments(t2, "en", "1")) == 5


def test_empty_and_symbols():
    assert segment.segments("   ", "en") == []
    assert segment.sentences("* * *", "en") == []


# ---------- matching ----------

def test_match_apostrophes_whitespace_case():
    text = "Se l’era cavata\n  da sola. L'Italia."
    assert match.find(text, "se l'era cavata", 0, len(text), lang="it") == (0, 15)
    assert match.find(text, "l’Italia", 0, len(text), lang="it") is not None


def test_match_word_boundary_and_taken():
    text = "cat concatenate cat"
    assert match.find(text, "cat", 0, len(text)) == (0, 3)
    assert match.find(text, "cat", 0, len(text), taken=[(0, 3)]) == (16, 19)
    assert match.find(text, "cat", 4, 15) is None


def test_match_cjk_substring():
    text = "他漫无目的地游荡。"
    assert match.find(text, "游荡", 0, len(text), lang="zh") == (6, 8)


# ---------- text nodes ----------

def P(s):
    return etree.fromstring(f'<p xmlns="http://www.w3.org/1999/xhtml">{s}</p>')


def test_collect_skips_rt_and_counts_br():
    p = P("A <ruby>漢<rt>かん</rt></ruby>字<br/>next")
    _, text = textnodes.collect(p)
    assert text == "A 漢字\nnext"


def test_wrap_inside_em_and_across_tags():
    p = P("a <em>dark and</em> stormy")
    _, text = textnodes.collect(p)
    s = text.index("dark")
    assert textnodes.wrap(p, s, s + 4, lambda w: etree.Element("ruby", {"class": "gbr"}))
    s2 = text.index("and stormy")
    assert not textnodes.wrap(p, s2, s2 + 10, lambda w: etree.Element("x"))


def test_insert_keeps_offsets_and_avoids_link():
    p = P('see <a href="#">the link</a> now. More.')
    _, text = textnodes.collect(p)
    mk = lambda: etree.Element("a", {"class": "gb-nr"})  # noqa: E731
    textnodes.insert_at(p, text.index("link") + 4, mk())     # lands inside <a> -> moved after it
    textnodes.insert_at(p, text.index("now.") + 4, mk())
    _, text2 = textnodes.collect(p)
    assert text2 == text
    links = [e for e in p.iter() if e.get("class") == "gb-nr"]
    assert all(e.getparent() is p for e in links)
    assert textnodes.wrap(p, text.index("More"), text.index("More") + 4, lambda w: etree.Element("b"))
