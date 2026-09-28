"""Generation: split into segments -> pack about chunk_words words per request -> call the model
concurrently (skipping anything cached) -> validate -> results."""
import concurrent.futures as cf
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from . import detect, layout, match, prompt, segment
from .prompt import Gloss, SegResult

MAX_FIX_ROUNDS = 2
INTRO_MAX_WORDS = 15000
INTRO_MIN_WORDS = 50
MAX_EXPRESSION_CHARS = 60


@dataclass
class Seg:
    id: str
    chapter: int
    block: int         # index into book.blocks (of the last part: the ¶ goes there)
    start: int         # span in the block's plain text
    end: int
    text: str          # original text with whitespace collapsed (what the model sees)
    parts: list = None     # [(block, start, end)] when the segment spans several lines of verse

    def spans(self):
        return self.parts or [(self.block, self.start, self.end)]


@dataclass
class Job:
    kind: str          # "seg" or "intro"
    key: str           # cache key
    chapter: int
    chunk: list = None       # [Seg] for "seg"
    context: str = ""        # previous segment, for "seg"
    text: str = ""           # chapter text, for "intro"


@dataclass
class Outcome:
    results: dict        # seg id -> SegResult
    intros: dict         # chapter index -> intro dict
    stats: dict


class Work:
    """Working directory: cache/, usage.jsonl, state.json."""

    def __init__(self, path):
        self.path = Path(path)
        self.cache = self.path / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.usage = self.path / "usage.jsonl"
        self.state_path = self.path / "state.json"

    def get(self, key):
        p = self.cache / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def put(self, key, data):
        p = self.cache / f"{key}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.is_file() else {}

    def save_state(self, data):
        self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def plan(book, chapters, s, lang):
    """{chapter index: [Seg]}. Headings are not annotated."""
    out = {}
    for ch in chapters:
        segs = []
        for parts, text in layout.chapter_segments(book, ch, lang, s.per_note, s.max_words):
            bi, start, end = parts[-1]
            segs.append(Seg(f"c{ch.index}-{len(segs)}", ch.index, bi, start, end, text,
                            parts if len(parts) > 1 else None))
        out[ch.index] = segs
    return out


def chunks(segs, chunk_words, lang):
    out, cur, n = [], [], 0
    for sg in segs:
        w = segment.units(sg.text, lang)
        if cur and n + w > chunk_words:
            out.append(cur)
            cur, n = [], 0
        cur.append(sg)
        n += w
    return out + ([cur] if cur else [])


def _key(*parts):
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def chunk_key(s, lang, chunk, context):
    gen = {k: v for k, v in s.gen().items() if k not in ("intro", "chunk_words")}
    if gen.get("translation", True):
        gen.pop("translation", None)     # keeps cache keys from before the setting existed
    return _key("seg", prompt.version(s), gen, lang, context, [c.text for c in chunk])


def intro_key(s, lang, text):
    return _key("intro", prompt.INTRO_PROMPT_VERSION, s.target, s.level, lang, text)


def _dump(results):
    return [{"tr": r.tr, "cu": r.cu, "gl": [[g.w, g.g, g.level, g.note, g.lemma] for g in r.gl]} for r in results]


def _load(data):
    return [SegResult(d["tr"], [Gloss(*g) for g in d["gl"]], d.get("cu", "")) for d in data]


def _check_glosses(results, texts, lang, stats):
    """Each expression must occur verbatim in its segment. If not, try the neighbouring segments;
    otherwise drop it (dropping is cheaper than a retry)."""
    def found(i, w):
        return match.find(texts[i], w, 0, len(texts[i]), lang=lang) is not None

    for i, r in enumerate(results):
        keep, seen = [], set()
        for g in r.gl:
            key = g.w.lower()
            if key in seen or len(g.w) > MAX_EXPRESSION_CHARS:
                stats["dropped"] += 1
            elif found(i, g.w):
                keep.append(g)
                seen.add(key)
            else:
                j = next((j for j in (i - 1, i + 1) if 0 <= j < len(texts) and found(j, g.w)), None)
                if j is None:
                    stats["dropped"] += 1
                else:
                    results[j].gl.append(g)
                    stats["moved"] += 1
        r.gl = keep


def gen_chunk(client, system, job, s, lang):
    """Returns (results, stats). Only the segments missing from the answer are re-requested."""
    texts = [c.text for c in job.chunk]
    stats = {"dropped": 0, "moved": 0, "missing": 0, "retries": 0}

    def ask(sub, retry):
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": prompt.user_prompt(sub, job.context)}]
        return prompt.parse(client.chat(msgs, "seg", job.chapter, retry=retry), s.target, s.culture, s.translation)

    def answered(got, i):
        return i in got and (got[i].tr or not s.translation)

    got = ask(texts, False)
    results = [got[i] if answered(got, i) else None for i in range(len(texts))]
    for _ in range(MAX_FIX_ROUNDS):
        missing = [i for i, r in enumerate(results) if r is None]
        if not missing:
            break
        stats["retries"] += 1
        again = ask([texts[i] for i in missing], True)
        for j, i in enumerate(missing):
            if answered(again, j):
                results[i] = again[j]
    stats["missing"] = sum(r is None for r in results)
    results = [r or SegResult() for r in results]
    _check_glosses(results, texts, lang, stats)
    return results, stats


def gen_intro(client, s, lang, job):
    text = job.text
    words = text.split()
    if len(words) > INTRO_MAX_WORDS:
        text = " ".join(words[:INTRO_MAX_WORDS])
    msgs = [{"role": "user", "content": prompt.intro_prompt(s, lang, text)}]
    intro = prompt.parse_intro(client.chat(msgs, "intro", job.chapter), s.target)
    if not detect.written_in(intro["summary"], s.target):     # some models drift into the book's language
        intro = prompt.parse_intro(client.chat(msgs, "intro", job.chapter, retry=True), s.target)
    low = match.norm(text).lower()
    intro["kw"] = [k for k in intro["kw"] if match.norm(k["w"]).lower() in low]   # keywords must be in the text
    return intro


def chapter_text(book, ch):
    return "\n\n".join(segment.normalize(b.text) for b in book.blocks[ch.start:ch.end])


def _collect_jobs(book, chapters, plans, s, lang, work, client, only_chunks, results, intros, stats):
    jobs = []
    for ch in chapters:
        segs = plans[ch.index]
        cks = chunks(segs, s.chunk_words, lang)
        if only_chunks is not None:
            cks = cks[:only_chunks.get(ch.index, 0)]
        pos = 0
        for ck in cks:
            context = segs[pos - 1].text if pos else ""
            pos += len(ck)
            key = chunk_key(s, lang, ck, context)
            stats["chunks"] += 1
            cached = work.get(key)
            if cached is not None and len(cached) == len(ck):
                results.update(zip((c.id for c in ck), _load(cached), strict=True))
                stats["cached"] += 1
            elif client is None:
                stats["uncached"] += 1
            else:
                jobs.append(Job("seg", key, ch.index, chunk=ck, context=context))
        if s.intro and (only_chunks is None or ch.index in only_chunks):
            text = chapter_text(book, ch)
            key = intro_key(s, lang, text)
            cached = work.get(key)
            if cached is not None:
                intros[ch.index] = cached
            elif client is not None and ch.words >= INTRO_MIN_WORDS:
                jobs.append(Job("intro", key, ch.index, text=text))
    return jobs


def run(book, chapters, s, lang, work, client=None, only_chunks=None, progress=print):
    """client=None: read the cache only (for `build`). only_chunks: {chapter: first N chunks} (preview).
    Returns (Outcome, plans)."""
    plans = plan(book, chapters, s, lang)
    system = prompt.system_prompt(s, lang)
    stats = dict.fromkeys(("chunks", "cached", "generated", "uncached", "skipped_budget",
                           "dropped", "moved", "missing", "retries"), 0)
    results, intros = {}, {}
    jobs = _collect_jobs(book, chapters, plans, s, lang, work, client, only_chunks, results, intros, stats)

    stop = threading.Event()

    def do(job):
        if stop.is_set() or (s.max_cost is not None and client.log.total_cost >= s.max_cost):
            return job, None, None
        if job.kind == "intro":
            return job, gen_intro(client, s, lang, job), None
        return job, *gen_chunk(client, system, job, s, lang)

    # Send one segment request alone first. Once it returns, the system prompt is in the provider's
    # prompt cache and the concurrent requests that follow hit it (cached input is ~1/30 the price).
    first = next((i for i, j in enumerate(jobs) if j.kind == "seg"), None)
    warm = first is not None and len(jobs) > 1 and s.jobs > 1
    if warm:
        jobs.insert(0, jobs.pop(first))
    ex = cf.ThreadPoolExecutor(max(1, s.jobs))
    try:
        futs = []
        if warm:
            futs.append(cf.Future())
            futs[0].set_result(do(jobs[0]))
        futs += [ex.submit(do, j) for j in jobs[int(warm):]]
        for done, fut in enumerate(cf.as_completed(futs), 1):
            job, res, st = fut.result()
            if res is None:
                stats["skipped_budget"] += 1
                continue
            if job.kind == "intro":
                intros[job.chapter] = res
                work.put(job.key, res)
            else:
                results.update(zip((c.id for c in job.chunk), res, strict=True))
                for k in ("dropped", "moved", "missing", "retries"):
                    stats[k] += st[k]
                if not st["missing"]:          # incomplete chunks are not cached, so a rerun retries them
                    work.put(job.key, _dump(res))
                stats["generated"] += 1
            progress(f"  [{done}/{len(jobs)}] cost so far {client.log.total_cost:.4f} USD")
    except BaseException:
        # A fatal API error or Ctrl-C: send no more requests (only those already in flight finish).
        stop.set()
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown()
    if stats["skipped_budget"]:
        progress(f"Cost limit {s.max_cost} reached; {stats['skipped_budget']} request(s) not sent "
                 "(run again to continue from here).")
    return Outcome(results, intros, stats), plans
