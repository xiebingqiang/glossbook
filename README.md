# glossbook

Turn a foreign-language EPUB into a learner's edition you can read on a Kindle or any e-reader —
without leaving the original text.

- **Ruby glosses**: short in-context meanings printed in small type above hard words, filtered by
  your CEFR level and a density setting; each word is glossed at most N times.
- **¶ notes** after every clause or sentence: the translation, notes on the hard words (base forms of
  irregular verbs, idioms, slang, register), and optional cultural/allusion notes.
- **Chapter guides**: a ¶ after each chapter heading with a spoiler-free summary, the main characters
  and key words.
- Personal and place names are left untranslated.

The output is a regular EPUB3 (popup footnotes + `<ruby>`), verified on a real Kindle and with
Kindle Previewer and epubcheck. [中文说明](README.zh-CN.md)

## Screenshots

The [sample](#sample) on a Kindle and in Apple Books.

<p><img src="images/apple-books-sample.png" width="100%" alt=""><br><sub>Apple Books: a part's divider page, and a ¶ note open over the text</sub></p>

<table>
<tr><td width="25%" valign="top"><img src="images/kindle-dickens-note.jpeg" width="100%" alt=""><br><sub>English → 中文, B1: rubies over hard words; a ¶ opens the translation and word notes</sub></td><td width="25%" valign="top"><img src="images/kindle-sonnet-note.jpeg" width="100%" alt=""><br><sub>Sonnet 18: verse lines joined into sentences; archaic thou / art explained</sub></td><td width="25%" valign="top"><img src="images/kindle-akutagawa-note.jpeg" width="100%" alt=""><br><sub>日本語 → 中文: Akutagawa, with rubies on Japanese text</sub></td><td width="25%" valign="top"><img src="images/kindle-pinocchio-guide.jpeg" width="100%" alt=""><br><sub>Italiano → English, A2: the ¶ after the title opens the chapter guide</sub></td></tr>
<tr><td width="25%" valign="top"><img src="images/kindle-maupassant-note.jpeg" width="100%" alt=""><br><sub>Français → English, B1: a long sentence split into clauses</sub></td><td width="25%" valign="top"><img src="images/kindle-kafka-b2.jpeg" width="100%" alt=""><br><sub>Deutsch → English, B2: one ¶ per sentence, fewer rubies</sub></td><td width="25%" valign="top"><img src="images/kindle-quijote-no-translation.jpeg" width="100%" alt=""><br><sub>Español → English, C1 with <code>--no-translation</code>: notes only</sub></td></tr>
</table>

## Sample

`samples/` builds a demo EPUB from six short public-domain texts, each annotated with different
languages and settings (DeepSeek v4-pro), then merged into one book with a divider page before each
part:

| Part | Text | Settings | What to look at |
|---|---|---|---|
| English → 中文 | Dickens, *A Christmas Carol* (opening); Shakespeare, Sonnet 18; Frost, *The Road Not Taken* | `--target zh --level B1` | rubies, a ¶ per clause, chapter guides; verse lines joined into sentences, archaic words (thee, hath) glossed |
| 日本語 → 中文 | Akutagawa, *The Spider's Thread* (蜘蛛の糸) | `--target zh --level B1` | Japanese segmentation, honorific forms and Buddhist terms explained |
| Italiano → English | Collodi, *Pinocchio*, ch. I | `--target en --level A2` | short clauses, dense rubies |
| Français → English | Maupassant, *La Parure* (opening) | `--target en --level B1` | long sentences split into clauses |
| Deutsch → English | Kafka, *Die Verwandlung* (opening) | `--target en --level B2` | one ¶ per sentence, fewer rubies |
| Español → English | Cervantes, *Don Quijote*, ch. 1 (opening) | `--target en --level C1 --no-translation` | notes on hard and archaic words only, no translation |

About 3,000 words in all; generating it cost about 0.08 USD. To build it yourself:

```
samples/fetch_sources.sh    # Project Gutenberg, Wikisource, Aozora Bunko -> samples/src/
samples/build_sample.sh     # six source EPUBs -> glossbook run (ds4pro) -> samples/glossbook-sample.epub
```

`make_sources.py` writes the source EPUBs to `samples/books/` (each annotated edition is written there
too and can be read on its own); `merge.py` joins the annotated editions.

## Install

Python 3.11+. Not on PyPI yet; install from GitHub (with [pipx](https://pipx.pypa.io/), so the
`glossbook` command is available everywhere):

```
pipx install git+https://github.com/xiebingqiang/glossbook
glossbook init --target zh    # writes ~/.config/glossbook/.env (API keys) and config.toml (defaults)
```

Put an API key in `~/.config/glossbook/.env`, then check it with `glossbook models` (lists models,
whether their key is set, and prices). `glossbook init --here` writes `./.env` and `./glossbook.toml`
instead, which take precedence when you run glossbook in that directory. Environment variables work
too.

For development: `git clone …`, then `pip install -e ".[dev]"`.

## Choosing a model

Any OpenAI-compatible API works. Models are defined in `glossbook/models.toml`:

| Name | Model | Key | Notes |
|---|---|---|---|
| `ds4pro` (default) | DeepSeek V4 Pro, official API | `DEEPSEEK_API_KEY` from [platform.deepseek.com](https://platform.deepseek.com) | best tested; reasoning off |
| `ds4flash` | DeepSeek Flash, official API | same | about a third of the cost; translations nearly as good, fewer glosses, the odd wrong one |
| `ds4pro-or` | DeepSeek V4 Pro via OpenRouter | `OPENROUTER_API_KEY` | one key for many providers |
| `gemini` | Gemini 2.5 Flash | `GEMINI_API_KEY` | works |
| `gpt`, `claude` | GPT-5 mini, Claude Sonnet 5 | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | untested examples |

Pick one with `--model`, `model = "…"` in the settings file, or `GLOSSBOOK_MODEL`. All costs are in
USD; prices are per million tokens in `models.toml` (DeepSeek's CNY prices converted at 7.1). To
add a model or change prices, copy the file to `~/.config/glossbook/models.toml` or `./models.toml`
and edit it. Per model you can also set `temperature = false` (send none) and
`max_tokens_param = "max_completion_tokens"`, which reasoning models such as gpt-5 need.

## Usage

```
glossbook inspect book.epub                          # chapter numbers, word counts, rough cost
glossbook preview book.epub --target zh --level B1   # annotate a sample -> preview.html + cost estimate
glossbook run book.epub --chapters 3-8               # same settings as the preview; asks before spending
glossbook build book.epub --level B2 --density low   # re-render from the cache, no API calls
glossbook report book.epub                           # token usage and cost
```

`preview` writes an HTML page where you can switch level and density to see the effect before
paying for the whole book (`--ui zh` for Chinese labels). The settings you give are remembered for
the book, so `run` needs no flags to match the preview (it reuses the sample from the cache); flags
you pass override them. `run` shows the estimate and asks before starting; in scripts pass `--yes`.
`--max-cost 2` stops at 2 USD.

Everything is cached per request in `<book>.glossbook/` next to the EPUB, so an interrupted run
(Ctrl-C, a network error, an empty account) continues where it stopped, and changing level, density
or repeat with `build` costs nothing. The output is written next to the book as
`book.<target>-<level>.epub` (`-o` to change).

## Reading it on a Kindle or other e-reader

- **Kindle**: send the output EPUB with [Send to Kindle](https://www.amazon.com/sendtokindle) (web,
  desktop app or e-mail); Amazon converts it. Ruby glosses and ¶ popup notes work on the device.
- **Kobo, Apple Books, KOReader, …**: open the EPUB directly.
- **Your book is AZW3/MOBI**: convert it to EPUB first, e.g. with [Calibre](https://calibre-ebook.com)
  (DRM-free books only).

## Settings

A level preset sets several options at once; any option you give explicitly wins.
Priority: built-in defaults < level preset < settings file (`./glossbook.toml`, else
`~/.config/glossbook/config.toml`, section `[settings]`) < settings remembered for this book < command line.

| Level | Sentences per ¶ | Max words per clause | Ruby density (one per N words) |
|---|---|---|---|
| A1 / A2 | clause | 15 / 20 | 7 / 9 |
| B1 (default) | clause | 25 | 12 |
| B2 | 1 | 35 | 20 |
| C1 | 2 | 50 | 35 |
| C2 | 3 | 60 | 60 |

A ¶ never spans two paragraphs: sentences are grouped only within a paragraph. The exception is
verse: when a poem has one line per paragraph (common in EPUBs), consecutive lines are read as one
text, so a ¶ covers a sentence (or 2–3 at higher levels) of the poem rather than a single line.

| Flag | Meaning |
|---|---|
| `--target` | language of translations and glosses (default `en`) |
| `--source` | language of the book (default: from the EPUB) |
| `--level` | reader's CEFR level, `A1`–`C2` |
| `--per-note` | `clause` (long sentences split at punctuation), `1`, `2`, `3` or `para` |
| `--density` | `low`, `normal`, `high`, or words per ruby |
| `--repeat` | max rubies per word (default 3) |
| `--culture` / `--no-culture` | cultural and allusion notes |
| `--intro` / `--no-intro` | chapter guides |
| `--translation` / `--no-translation` | translation in each ¶ note (off: glosses and cultural notes only, ~20% cheaper; `build --no-translation` hides translations already generated) |
| `--model` | a model name from `models.toml` |
| `--jobs` | concurrent requests (default 8) |
| `--max-cost` | stop when this cost (USD) is reached |
| `--chunk-words` | words per request (default 300) |

Supported: EPUB input; space-delimited languages, Chinese and Japanese (as source or target).
Not supported: right-to-left languages, DRM-protected files.

Layouts handled: prose, verse (one line per paragraph or lines split by `<br/>`), plays, notes with
footnote markers (`<sup>[1]</sup>`, numbers glued to a word) and print page numbers
(`<span class="origpage">[12]</span>`, `epub:type="pagebreak"`), all hidden from the model;
stanza and chapter numbers (not annotated), bilingual books (paragraphs in another script are
skipped). A wrong or missing `dc:language` (many converters write `en` for everything) is detected
from the text and replaced, with a message; `--source` always wins. A table of contents with a
single entry falls back to one chapter per file.

## Cost

Measured with `ds4pro` (September 2026):

- Italian → Chinese, B1: about 0.025 USD per 1,000 words including chapter guides (a 87,000-word
  novel: about 2.1 USD)
- English → Chinese, B2: about 0.01 USD per 1,000 words
- Latin → Chinese, B1: about 0.04 USD per 1,000 words (nearly every word gets a gloss: about 30–40
  per 100 words, with case and form notes)

For a book you mostly read without help, `--level C2 --no-translation --no-intro` keeps only a few
glosses (about 3 per 100 words: rare, literary and archaic words). On *Pride and Prejudice* this
costs under half of the B1 default (about 0.83 vs 1.75 USD for the book); input tokens (the model still reads every sentence) set the floor.

With `ds4flash` the same Italian novel is estimated at about 0.6 USD (about 30%).

Token use is kept low by segmenting in code (the model never copies text back), a compact line
format instead of JSON, a stable system prompt for provider-side prompt caching (one request goes
first to warm the cache), retrying only missing segments, and turning reasoning off.

## How it works

1. `epub.py` / `chapters.py` read the EPUB and map the table of contents to text blocks.
2. `segment.py` splits blocks into sentences or clauses; `pipeline.py` packs them into requests
   and calls the model concurrently; `prompt.py` parses the line format.
3. `placement.py` decides which glosses get a ruby; `render.py` inserts `<ruby>` and ¶ links into
   the original XHTML without touching the rest of the markup; `package.py` writes the EPUB3.

## Development

```
python3 -m pytest -q
ruff check
```

Tests build their EPUBs on the fly and use a fake model client; no network access is needed.

## Copyright

Only process books you are allowed to. The annotated output contains the full original text plus a
translation; don't redistribute annotated editions of copyrighted books. DRM-protected files are
rejected.

## License

[GNU Affero General Public License v3.0 or later](LICENSE). If you run a modified version as a
network service, you must offer its source code to the service's users.
