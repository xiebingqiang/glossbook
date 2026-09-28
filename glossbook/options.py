"""Command-line settings: the shared flags, the working directory, settings remembered per book,
and the source language check."""
import argparse
import json
import sys
from pathlib import Path

from . import config, detect
from . import languages as L
from .config import ConfigError

SETTING_FLAGS = ("target", "source", "level", "density", "per_note", "max_words", "repeat",
                 "culture", "intro", "translation", "model", "jobs", "max_cost", "chunk_words")
DISPLAY_KEYS = ("level", "density", "repeat")   # can change at build time without regenerating
REMEMBERED = tuple(k for k in SETTING_FLAGS if k not in ("jobs", "max_cost"))   # kept per book in state.json


def add_settings(p):
    g = p.add_argument_group("settings (default: level preset, then glossbook.toml)")
    g.add_argument("--target", help="language of translations and glosses (default: en)")
    g.add_argument("--source", help="language of the book (default: dc:language of the EPUB)")
    g.add_argument("--level", help="reader's CEFR level A1–C2 (default: B1); selects a preset")
    g.add_argument("--density", help="ruby density: low / normal / high, or words per ruby")
    g.add_argument("--per-note", dest="per_note", help="sentences per ¶ note: clause / 1 / 2 / 3 / para")
    g.add_argument("--max-words", dest="max_words", type=int, help="max words per clause in clause mode")
    g.add_argument("--repeat", type=int, help="max rubies per word (default: 3)")
    g.add_argument("--culture", action=argparse.BooleanOptionalAction, default=None,
                   help="cultural notes and allusions")
    g.add_argument("--intro", action=argparse.BooleanOptionalAction, default=None, help="chapter guides")
    g.add_argument("--translation", action=argparse.BooleanOptionalAction, default=None,
                   help="translation in each ¶ note (off: glosses and cultural notes only; fewer output tokens)")
    g.add_argument("--model", help="model name from models.toml (default: ds4pro)")
    g.add_argument("--jobs", type=int, help="concurrent requests (default: 8)")
    g.add_argument("--max-cost", dest="max_cost", type=float, help="stop once this cost is reached (USD)")
    g.add_argument("--chunk-words", dest="chunk_words", type=int, help="words per request (default: 300)")


def cli_settings(args):
    return {k: getattr(args, k, None) for k in SETTING_FLAGS}


def work_dir(args):
    return Path(args.work) if getattr(args, "work", None) else Path(args.book).with_suffix(".glossbook")


def book_settings(args):
    """Settings for inspect/preview/run: what the last preview or run of this book was given
    explicitly (state.json), then the command line. Returns (Settings, explicit settings to remember)."""
    state_path = work_dir(args) / "state.json"
    saved = json.loads(state_path.read_text(encoding="utf-8")).get("settings", {}) if state_path.is_file() else {}
    cli = {k: v for k, v in cli_settings(args).items() if v is not None}
    kept = {k: v for k, v in saved.items() if k not in cli}
    if kept:
        print("Settings remembered for this book: " + ", ".join(f"{k}={v}" for k, v in kept.items())
              + " (command-line flags override)")
    return config.resolve({**saved, **cli}), {**saved, **{k: v for k, v in cli.items() if k in REMEMBERED}}


def source_lang(book, s):
    """--source, else dc:language; a missing or clearly wrong dc:language is replaced by the language
    detected from the text (with a message)."""
    lang = s.source
    if not lang:
        lang, note = detect.check_declared(book, book.lang)
        if note:
            print(note, file=sys.stderr)
    if not lang:
        raise ConfigError("the EPUB has no dc:language; set the book's language with --source")
    for code, what in ((lang, "source"), (s.target, "target")):
        if L.is_rtl(code):
            raise ConfigError(f"right-to-left languages are not supported yet ({what} language {code})")
        if not L.known(code):
            print(f"Warning: unknown language code {code!r}; treating it as space-delimited", file=sys.stderr)
    return L.base(lang)


def calibrated(state, m):
    """Cost per word measured by the last preview, if it used the same model."""
    cal = state.get("calibration", {})
    return cal.get("cost_per_word") if cal.get("model") == m["name"] and cal.get("currency") == "USD" else None
