"""Token usage: log every call, compute cost, summarize, and estimate before a run."""
import json
import threading
import time
from collections import defaultdict
from pathlib import Path

# Estimation factors used before a preview has measured the real ratio (ds4pro, 2026-09), in
# tokens per word (2 CJK characters count as one word). Output varies a lot with the level:
# Italian -> Chinese at B1 was about 5.2 tokens/word, English -> Chinese at B2 about 1.9.
IN_PER_WORD = 1.5
OUT_PER_WORD = {"A1": 5.5, "A2": 5.5, "B1": 5.0, "B2": 2.5, "C1": 1.8, "C2": 1.5}
PREFIX_TOKENS = 800
NO_TRANSLATION_OUT = 0.66   # share of output tokens left without translations (measured en→zh B1)
KEYS = ("calls", "prompt", "cached", "completion", "reasoning", "cost")


def from_response(resp):
    """Handles DeepSeek (prompt_cache_hit_tokens) and OpenAI/OpenRouter
    (prompt_tokens_details.cached_tokens)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return {"prompt": 0, "cached": 0, "completion": 0, "reasoning": 0}
    cached = getattr(u, "prompt_cache_hit_tokens", None)
    if cached is None:
        details = getattr(u, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
    cdetails = getattr(u, "completion_tokens_details", None)
    return {"prompt": u.prompt_tokens or 0, "cached": cached or 0,
            "completion": u.completion_tokens or 0,
            "reasoning": (getattr(cdetails, "reasoning_tokens", 0) or 0) if cdetails else 0}


def cost(rec, price):
    if not price:
        return 0.0
    uncached = rec["prompt"] - rec["cached"]
    return (uncached * price.get("input", 0) + rec["cached"] * price.get("input_cached", price.get("input", 0))
            + rec["completion"] * price.get("output", 0)) / 1e6


class UsageLog:
    """Thread-safe; every record is appended to usage.jsonl."""

    def __init__(self, path=None, price=None):
        self.path = Path(path) if path else None
        self.price = price or {}
        self.records = []
        self.lock = threading.Lock()

    def add(self, model, kind, chapter, u, retry=False):
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "kind": kind,
               "chapter": chapter, "retry": retry, **u, "currency": "USD"}
        rec["cost"] = round(cost(rec, self.price), 6)
        with self.lock:
            self.records.append(rec)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    @property
    def total_cost(self):
        with self.lock:
            return sum(r["cost"] for r in self.records)


def load(path):
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(records):
    total, retry = dict.fromkeys(KEYS, 0), dict.fromkeys(KEYS, 0)
    by = defaultdict(lambda: dict.fromkeys(KEYS, 0))
    for r in records:
        for bucket in [total, by[(r["model"], r.get("chapter"))]] + ([retry] if r.get("retry") else []):
            bucket["calls"] += 1
            for k in KEYS[1:]:
                bucket[k] += r.get(k, 0)
    return total, dict(by), retry


def report(records):
    if not records:
        return "No calls recorded yet."
    total, by, retry = summarize(records)
    cur = " USD"
    lines = [f"{'model':<14}{'ch':>4}{'calls':>6}{'input':>10}{'cached':>10}{'output':>9}{'reason':>7}{'cost USD':>10}"]
    for (model, ch), b in sorted(by.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None else kv[0][1])):
        lines.append(f"{model:<14}{str(ch):>4}{b['calls']:>6}{b['prompt']:>10}{b['cached']:>10}"
                     f"{b['completion']:>9}{b['reasoning']:>7}{b['cost']:>10.4f}")
    hit = total["cached"] / total["prompt"] * 100 if total["prompt"] else 0
    lines.append(f"Total: {total['calls']} calls, input {total['prompt']} ({hit:.0f}% cache hits), "
                 f"output {total['completion']}, reasoning {total['reasoning']}, cost {total['cost']:.4f}{cur}")
    if retry["calls"]:
        share = retry["cost"] / total["cost"] * 100 if total["cost"] else 0
        lines.append(f"Retries: {retry['calls']} calls, cost {retry['cost']:.4f}{cur} ({share:.0f}%)")
    old = sum(1 for r in records if r.get("currency") != "USD")
    if old:
        lines.append(f"Note: {old} older record(s) were logged before costs were in USD (DeepSeek models: CNY)")
    if total["reasoning"]:
        lines.append("Warning: reasoning tokens were used; the model's reasoning switch may not work "
                     "(see extra_body in models.toml)")
    return "\n".join(lines)


def estimate(words, s, price, calibrated=None):
    """calibrated: {"cost_per_word": x} measured by a preview. Returns dict(calls, prompt, completion, cost)."""
    calls = max(1, round(words / s.chunk_words)) if words else 0
    prompt = int(words * IN_PER_WORD + calls * PREFIX_TOKENS)
    out = int(words * OUT_PER_WORD.get(s.level, 3.0) * (1 if s.translation else NO_TRANSLATION_OUT))
    cached = (calls - 1) * PREFIX_TOKENS if calls > 1 else 0
    c = cost({"prompt": prompt, "cached": cached, "completion": out}, price)
    if calibrated and calibrated.get("cost_per_word"):
        c = calibrated["cost_per_word"] * words
    return {"calls": calls, "prompt": prompt, "completion": out, "cost": c}
