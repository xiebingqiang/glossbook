"""Settings merge, line-format parsing, ruby placement."""
import pytest

from glossbook import config, pipeline, placement, prompt, render
from glossbook.config import ConfigError
from glossbook.pipeline import Seg
from glossbook.prompt import Gloss, SegResult

# ---------- settings ----------

def test_level_preset_and_overrides():
    s = config.resolve({}, from_file={})
    assert (s.level, s.per_note, s.max_words, s.density) == ("B1", "clause", 25, 12)
    s = config.resolve({"level": "c1"}, from_file={})
    assert (s.per_note, s.density) == ("2", 35)
    s = config.resolve({"level": "C1", "per_note": "clause"}, from_file={"density": "high", "level": "A2"})
    assert (s.level, s.per_note, s.density) == ("C1", "clause", 17.5)   # CLI level beats the file; the file density still applies


@pytest.mark.parametrize("bad", [{"level": "D1"}, {"per_note": "4"}, {"density": "lots"}, {"jobs": 0},
                                 {"density": -1}])
def test_bad_settings(bad):
    with pytest.raises(ConfigError):
        config.resolve(bad, from_file={})


def test_unknown_file_setting():
    with pytest.raises(ConfigError, match="unknown setting"):
        config.resolve({}, from_file={"colour": "red"})


def test_env_loading(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# c\nexport GB_TEST_A="1"\nGB_TEST_B=two\nbad line\n')
    monkeypatch.setenv("GB_TEST_B", "keep")
    config.load_env([env])
    import os
    assert os.environ["GB_TEST_A"] == "1" and os.environ["GB_TEST_B"] == "keep"


def test_builtin_models_have_default():
    models, default = config.load_models()
    assert default == "ds4pro" and models["ds4pro"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert models["ds4pro-or"]["extra_body"]["reasoning"] == {"effort": "none"}
    assert all("currency" not in m.get("price", {}) for m in models.values())


def test_prices_must_be_usd(tmp_path):
    f = tmp_path / "m.toml"
    f.write_text('[models.x]\nbase_url = "u"\nmodel = "m"\nkey_env = "K"\nprice = { input = 1, currency = "CNY" }\n')
    with pytest.raises(ConfigError, match="USD"):
        config.load_models([f])


def test_model_params_and_status_errors():
    import httpx
    import openai

    from glossbook import llm, usage
    cfg = {"name": "g", "model": "m", "base_url": "http://x", "key_env": "K", "api_key": "k"}
    assert llm.Client(cfg, usage.UsageLog()).params() == {"temperature": 0.3, "max_tokens": 8000}
    c = llm.Client({**cfg, "temperature": False, "max_tokens_param": "max_completion_tokens"}, usage.UsageLog())
    assert c.params() == {"max_completion_tokens": 8000}

    def broke(**kw):
        resp = httpx.Response(402, request=httpx.Request("POST", "http://x"))
        raise openai.APIStatusError("Insufficient Balance", response=resp, body=None)
    c.api.chat.completions.create = broke
    with pytest.raises(llm.LLMError, match="insufficient balance"):
        c.chat([{"role": "user", "content": "hi"}])


# ---------- line format ----------

def test_parse_tolerant():
    raw = """```
[0] He left
  in a hurry.
- se n'è andato | left | b2 | andarsene |
- in fretta | in a hurry | B1
* A reference to Dante.
[2] Third.
- solo campo
```"""
    r = prompt.parse(raw, "en")
    assert r[0].tr == "He left in a hurry."
    assert [(g.w, g.level, g.note) for g in r[0].gl] == [("se n'è andato", "B2", "andarsene"), ("in fretta", "B1", "")]
    assert r[0].cu == "A reference to Dante."
    assert 1 not in r and r[2].gl == []
    assert prompt.parse(raw, "en", culture=False)[0].cu == ""


def test_parse_chinese_quotes():
    r = prompt.parse('[0] 他说"好"。\n- ok | "好" | A2 | |', "zh")
    assert r[0].tr == "他说“好”。" and r[0].gl[0].g == "“好”"


def test_intro_parse():
    it = prompt.parse_intro("S: Something happens.\nP: Anna — a teacher\nK: sabbia | sand\nK: bad line", "en")
    assert it == {"summary": "Something happens.", "who": ["Anna — a teacher"], "kw": [{"w": "sabbia", "g": "sand"}]}


def test_system_prompt_switches():
    s = config.resolve({"target": "zh", "culture": False}, from_file={})
    sp = prompt.system_prompt(s, "it")
    assert "Chinese" in sp and "Italian" in sp and "* <note>" not in sp and "我父亲" in sp
    s2 = config.resolve({"target": "fr"}, from_file={})
    assert "* <note>" in prompt.system_prompt(s2, "de")


# ---------- ruby placement ----------

class FakeBlock:
    def __init__(self, text):
        self.text, self.heading = text, False


class FakeBook:
    def __init__(self, texts):
        self.blocks = [FakeBlock(t) for t in texts]


def _setup(glosses, text="alpha beta gamma delta epsilon zeta eta theta iota kappa"):
    book = FakeBook([text])
    seg = Seg("c1-0", 1, 0, 0, len(text), text)
    return book, {1: [seg]}, {"c1-0": SegResult("tr", glosses)}


def test_level_filter_and_density():
    gl = [Gloss("alpha", "a", "C2"), Gloss("beta", "b", "B2"), Gloss("gamma", "g", "B1"),
          Gloss("delta", "d", "A1"), Gloss("nothere", "x", "C1")]
    book, plans, res = _setup(gl)
    s = config.resolve({"level": "B1", "density": 1}, from_file={})
    placed = placement.choose(book, plans, res, s, "en")["c1-0"]
    by = {p.gloss.w: p for p in placed}
    assert "delta" not in by                           # two levels below the reader: hidden entirely
    assert by["alpha"].ruby and by["beta"].ruby and not by["gamma"].ruby
    assert by["nothere"].span is None and not by["nothere"].ruby
    s = config.resolve({"level": "B1", "density": 100}, from_file={})
    placed = placement.choose(book, plans, res, s, "en")["c1-0"]
    assert [p.gloss.w for p in placed if p.ruby] == ["alpha"]   # low density: only the highest level gets a ruby



def test_c2_reader_gets_rubies_for_c2():
    book, plans, res = _setup([Gloss("alpha", "a", "C2"), Gloss("beta", "b", "C1"), Gloss("gamma", "g", "B2")])
    s = config.resolve({"level": "C2", "density": 1}, from_file={})
    by = {p.gloss.w: p for p in placement.choose(book, plans, res, s, "en")["c1-0"]}
    assert by["alpha"].ruby and by["beta"].ruby and "gamma" not in by

def test_repeat_limit_and_long_gloss():
    texts = ["foo bar"] * 5
    book = FakeBook(texts)
    plans = {1: [Seg(f"c1-{i}", 1, i, 0, 7, "foo bar") for i in range(5)]}
    res = {f"c1-{i}": SegResult("t", [Gloss("foo", "f", "C1", "", "fooo"), Gloss("bar", "a very long gloss indeed yes", "C1")])
           for i in range(5)}
    s = config.resolve({"density": 1, "repeat": 2}, from_file={})
    placed = placement.choose(book, plans, res, s, "en")
    assert sum(p.ruby for v in placed.values() for p in v if p.gloss.w == "foo") == 2
    assert not any(p.ruby for v in placed.values() for p in v if p.gloss.w == "bar")


def test_no_translation_parse_and_prompt():
    s = config.resolve({"target": "zh", "translation": False}, from_file={})
    sp = prompt.system_prompt(s, "it")
    assert "translation:" not in sp and "我父亲" not in sp
    res = prompt.parse("[0]\n[1] stray text\n- fu | 是 | B1 | |", "zh", translation=False)
    assert res[0].tr == "" and res[1].tr == "" and res[1].gl[0].w == "fu"


def test_translation_key_unchanged_when_on():
    on = config.resolve({}, from_file={})
    off = config.resolve({"translation": False}, from_file={})
    seg = pipeline.Seg("c1-0", 1, 0, 0, 5, "Ciao.")
    gen = {k: v for k, v in on.gen().items() if k not in ("intro", "chunk_words", "translation")}
    old = pipeline._key("seg", pipeline.prompt.PROMPT_VERSION, gen, "it", "", ["Ciao."])
    assert pipeline.chunk_key(on, "it", [seg], "") == old
    assert pipeline.chunk_key(off, "it", [seg], "") != old


def test_has_note_without_translation():
    assert render.has_note(SegResult("x"), [], True)
    assert not render.has_note(SegResult(""), [], True)
    assert not render.has_note(SegResult(""), [], False)
    assert render.has_note(SegResult("", cu="note"), [], False)
    assert render.has_note(SegResult("x"), ["placed"], False)


def test_note_skips_plain_rubies():
    Placed = placement.Placed
    plain, noted, off = (Placed(Gloss("a", "A", "C1", "", ""), (0, 1), True),
                         Placed(Gloss("b", "B", "C1", "why", ""), (2, 3), True),
                         Placed(Gloss("c", "C", "B2", "", ""), (4, 5), False))
    assert [p.gloss.w for p in render.note_glosses([plain, noted, off])] == ["b", "c"]
    assert not render.has_note(SegResult(""), render.note_glosses([plain]), False)   # no ¶ at all
    rows = render.seg_rows(SegResult("tr"), [plain], "en", "Note")
    assert rows == [("gb-zh", "tr")]
