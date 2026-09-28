"""Command line: init / models / inspect / preview / run / build / report."""
import argparse
import sys
from pathlib import Path

from . import (
    __version__,
    chapters,
    config,
    options,
    package,
    pipeline,
    placement,
    preview,
    render,
    scaffold,
    segment,
    usage,
)
from . import languages as L
from .config import ConfigError
from .epub import EpubError
from .llm import Client, LLMError

PREVIEW_MIN_WORDS = 150


def _client(s, work):
    m = config.pick_model(s.model)
    s.model = m["name"]
    return Client(m, usage.UsageLog(work.usage, m.get("price"))), m


def cmd_inspect(args):
    s, _ = options.book_settings(args)
    book = chapters.open_book(args.book)
    lang = options.source_lang(book, s)
    chosen = chapters.select(book, args.chapters)
    print(f"Title: {book.title}\nLanguage: {book.lang or '?'} (treated as {L.name(lang)}); EPUB {book.version}; "
          f"{len(book.docs)} content files, {len(book.chapters)} chapters (* = selected)")
    ids = {c.index for c in chosen}
    for c in book.chapters:
        print(f" {'*' if c.index in ids else ' '}{c.index:>3}  {c.words:>7} words  {c.title[:60]}")
    m = config.pick_model(s.model)
    words = sum(c.words for c in chosen)
    est = usage.estimate(words, s, m.get("price"))
    print(f"Selected: {len(chosen)} chapters, {words} words. Rough estimate with {m['name']}: {est['calls']} requests, "
          f"~{est['prompt']} input and ~{est['completion']} output tokens, ~{est['cost']:.2f} USD "
          "(run `preview` for a measured estimate)")


def _preview_chapter(book, chosen, index):
    if index is None:
        return next((c for c in chosen if c.words >= PREVIEW_MIN_WORDS), chosen[0])
    ch = next((c for c in book.chapters if c.index == index), None)
    if ch is None:
        raise ConfigError(f"no chapter {index}")
    return ch


def cmd_preview(args):
    s, explicit = options.book_settings(args)
    book = chapters.open_book(args.book)
    lang = options.source_lang(book, s)
    chosen = chapters.select(book, args.chapters)
    ch = _preview_chapter(book, chosen, args.chapter)
    work = pipeline.Work(options.work_dir(args))
    client, m = _client(s, work)
    plans = pipeline.plan(book, [ch], s, lang)
    n, words = 0, 0
    for ck in pipeline.chunks(plans[ch.index], s.chunk_words, lang):
        if words >= args.words:
            break
        n += 1
        words += sum(segment.units(sg.text, lang) for sg in ck)
    print(f"Preview: chapter {ch.index} ({ch.title}), first {n} chunk(s), ~{words} words, model {m['name']}")
    outcome, plans = pipeline.run(book, [ch], s, lang, work, client, only_chunks={ch.index: n})

    seg_cost = sum(r["cost"] for r in client.log.records if r["kind"] == "seg")
    intro_cost = sum(r["cost"] for r in client.log.records if r["kind"] == "intro")
    state = work.state()
    if seg_cost and words:
        state["calibration"] = {"cost_per_word": seg_cost / words, "model": m["name"], "currency": "USD"}
    state.update(gen=s.gen(), settings=explicit)
    work.save_state(state)
    total = sum(c.words for c in chosen)
    cpw = options.calibrated(state, m)
    est = usage.estimate(total, s, m.get("price"), {"cost_per_word": cpw} if cpw else None)
    est_cost = est["cost"] + (intro_cost * len(chosen) if s.intro else 0)
    info = [("Book", book.title), ("Languages", f"{L.name(lang)} → {L.name(s.target)}"), ("Model", m["name"]),
            ("Level / per ¶", f"{s.level} / {s.per_note}"),
            ("Translation / cultural notes / guides",
             " / ".join("on" if x else "off" for x in (s.translation, s.culture, s.intro))),
            ("Sample", f"chapter {ch.index}, first ~{words} words"),
            ("Sample cost", f"{client.log.total_cost:.4f} USD (cached parts are free)"),
            ("All selected chapters", f"{len(chosen)} chapters, {total} words, ~{est_cost:.2f} USD")]
    out = Path(args.out or work.path / "preview.html")
    out.write_text(preview.build(book, [ch], plans, outcome, s, lang, info, f"{book.title} · preview", args.ui),
                   encoding="utf-8")
    print(usage.report(client.log.records))
    print(f"Preview written to {out}\nAll selected chapters: {total} words, ~{est_cost:.2f} USD. "
          "If it looks right, run `glossbook run` on this book; it uses the same settings and reuses the sample.")


def _output_path(args, s):
    if getattr(args, "out", None):
        return Path(args.out)
    b = Path(args.book)
    return b.with_name(f"{b.stem}.{L.base(s.target)}-{s.level}.epub")


def _finish(book, chosen, plans, outcome, s, lang, out):
    placed = placement.choose(book, plans, outcome.results, s, lang)
    notes = render.apply(book, chosen, plans, outcome, placed, s)
    first = next((book.blocks[c.start].doc for c in chosen if c.end > c.start), 0)
    package.write(book, out, notes, s, first)
    st = placement.stats(placed, plans, lang)
    missing = sum(1 for segs in plans.values() for sg in segs
                  if sg.id not in outcome.results or (s.translation and not outcome.results[sg.id].tr))
    print(f"Wrote {out}\n{st['words']} words, {st['glosses']} glosses, {st['rubies']} rubies "
          f"({st['gloss_per_100']} / {st['ruby_per_100']} per 100 words)")
    if missing:
        print(f"Warning: {missing} segment(s) were not generated (or failed) and get no ¶; "
              "run again to fill them in")


def cmd_run(args):
    s, explicit = options.book_settings(args)
    book = chapters.open_book(args.book)
    lang = options.source_lang(book, s)
    chosen = chapters.select(book, args.chapters)
    work = pipeline.Work(options.work_dir(args))
    client, m = _client(s, work)
    dry, _ = pipeline.run(book, chosen, s, lang, work, None)
    todo_words = int(sum(c.words for c in chosen) * dry.stats["uncached"] / max(1, dry.stats["chunks"]))
    cpw = options.calibrated(work.state(), m)
    est = usage.estimate(todo_words, s, m.get("price"), {"cost_per_word": cpw} if cpw else None)
    limit = f" (limit {s.max_cost})" if s.max_cost is not None else ""
    print(f"{len(chosen)} chapters; {dry.stats['cached']} of {dry.stats['chunks']} chunks cached; "
          f"~{todo_words} words to generate, ~{est['cost']:.2f} USD{limit}")
    if not args.yes and dry.stats["uncached"]:
        if not sys.stdin.isatty():
            raise ConfigError("not running in a terminal, so can't ask for confirmation; add --yes to start")
        if input("Start? [y/N] ").strip().lower() not in ("y", "yes"):
            return
    outcome, plans = pipeline.run(book, chosen, s, lang, work, client)
    state = work.state()
    state.update(gen=s.gen(), settings=explicit, chapters=args.chapters or "all")
    work.save_state(state)
    print(usage.report(client.log.records))
    st = outcome.stats
    if st["dropped"] or st["retries"]:
        print(f"Validation: {st['retries']} retries, {st['dropped']} glosses dropped (not in the text), "
              f"{st['moved']} moved to a neighbouring segment")
    _finish(book, chosen, plans, outcome, s, lang, _output_path(args, s))


def cmd_build(args):
    work = pipeline.Work(options.work_dir(args))
    gen = work.state().get("gen")
    if not gen:
        raise ConfigError("nothing generated for this book yet (no state.json); use `run` first")
    cli = options.cli_settings(args)
    hide_tr = cli["translation"] is False and gen.get("translation", True)   # hiding needs no new calls
    for k, v in cli.items():
        was = gen.get(k, True) if k == "translation" else gen.get(k, v)   # older state.json has no translation
        if v is not None and k not in options.DISPLAY_KEYS and was != v and not (k == "translation" and hide_tr):
            raise ConfigError(f"{k} changes what the model generates; use `run` instead of `build`")
    s = config.resolve({**gen, **{k: cli[k] for k in options.DISPLAY_KEYS if cli[k] is not None}}, from_file={})
    s.translation = s.translation and not hide_tr
    if config.LEVELS.index(s.level) < config.LEVELS.index(gen["level"]):
        print(f"Warning: glosses were generated for {gen['level']}; building for the lower level {s.level} "
              f"will be sparse. For more glosses, `run` again with --level {s.level}")
    book = chapters.open_book(args.book)
    lang = options.source_lang(book, s)
    chosen = chapters.select(book, args.chapters or work.state().get("chapters"))
    outcome, plans = pipeline.run(book, chosen, config.resolve(gen, from_file={}), lang, work, None)
    if outcome.stats["uncached"]:
        print(f"Warning: {outcome.stats['uncached']} chunk(s) were never generated and stay unannotated")
    _finish(book, chosen, plans, outcome, s, lang, _output_path(args, s))


def cmd_report(args):
    print(usage.report(usage.load(pipeline.Work(options.work_dir(args)).usage)))


COMMANDS = {
    "inspect": ("list chapters and word counts, rough cost estimate", cmd_inspect),
    "preview": ("annotate a short sample into an HTML preview with a cost estimate", cmd_preview),
    "run": ("generate annotations and write the EPUB", cmd_run),
    "build": ("rewrite the EPUB from the cache only (level/density/repeat may change)", cmd_build),
    "report": ("token usage and cost", cmd_report),
}


def parser():
    ap = argparse.ArgumentParser(prog="glossbook",
                                 description="Annotate foreign-language EPUBs for learners: ruby glosses, "
                                             "per-sentence translation notes, chapter guides.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="write templates for API keys (.env) and default settings")
    p.set_defaults(func=scaffold.cmd_init)
    p.add_argument("--target", default="en", help="default language of translations and glosses (default: en)")
    p.add_argument("--here", action="store_true",
                   help="write ./.env and ./glossbook.toml instead of ~/.config/glossbook/.env and config.toml")
    sub.add_parser("models", help="list models, API key status and prices").set_defaults(func=scaffold.cmd_models)
    for name, (hlp, func) in COMMANDS.items():
        p = sub.add_parser(name, help=hlp)
        p.set_defaults(func=func)
        p.add_argument("book")
        p.add_argument("--work", help="working directory (default: <book>.glossbook/)")
        if name == "report":
            continue
        p.add_argument("--chapters", help="chapters, e.g. 1-3,5,8- (default: all; numbers from `inspect`)")
        options.add_settings(p)
        if name != "inspect":
            p.add_argument("-o", "--out", help="output file")
        if name == "preview":
            p.add_argument("--chapter", type=int, help="chapter to preview (default: first selected with text)")
            p.add_argument("--words", type=int, default=400, help="words to preview (default: 400)")
            p.add_argument("--ui", choices=sorted(preview.TEXT), default="en",
                           help="language of the preview page (default: en)")
        if name == "run":
            p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    config.load_env()
    try:
        args.func(args)
    except (ConfigError, EpubError, LLMError, ValueError) as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\nInterrupted. Finished chunks are cached; run again to continue.")


if __name__ == "__main__":
    main()
