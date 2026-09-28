"""Prompts and the compact line format.

Request:  [n] segment text
Answer:   [n] translation
          - expression | gloss | CEFR | note | lemma
          * cultural note
The line format needs about 40% fewer output tokens than JSON (no keys, no quoting).
"""
import re
from dataclasses import dataclass, field

from . import languages as L

PROMPT_VERSION = 3          # segment prompts; bump when their text changes (old cache entries are then unused)
C2_PROMPT_VERSION = 2       # the C2 wording of the choice rule, versioned alone so other levels keep their cache
INTRO_PROMPT_VERSION = 2    # chapter-guide prompt, versioned separately so its changes keep the segment cache
LEVEL_RE = re.compile(r"\b([ABC][12])\b", re.I)
MAX_INTRO_ITEMS = 5


@dataclass
class Gloss:
    w: str             # expression as written in the text
    g: str             # short gloss in the target language
    level: str = ""    # CEFR level of the expression
    note: str = ""
    lemma: str = ""


@dataclass
class SegResult:
    tr: str = ""                                 # translation
    gl: list = field(default_factory=list)       # [Gloss]
    cu: str = ""                                 # cultural note


EXAMPLE_IN = "[0] Mio padre è morto l’anno scorso.\n[1] Non ci fu nessuna cerimonia: se l’era cavata da solo, senza fronzoli, come sempre."
EXAMPLE_OUT = {
    "en": "[0] My father died last year.\n[1] There was no ceremony: he had managed on his own, without frills, as always.\n"
          "- fu | was | B1 | passato remoto of essere | essere\n"
          "- se l’era cavata | had got by | B2 | cavarsela = to manage | cavarsela\n"
          "- fronzoli | frills | C1 | | fronzolo",
    "zh": "[0] 我父亲去年去世了。\n[1] 没有举行任何仪式：他一向如此，不事铺张，自己应付过去了。\n"
          "- fu | 是 | B1 | essere 的远过去时 | essere\n"
          "- se l’era cavata | 应付过去 | B2 | cavarsela：设法应付 | cavarsela\n"
          "- fronzoli | 花哨装饰 | C1 | | fronzolo",
}


def _limits(target):
    if L.is_cjk(target) or L.base(target) == "ko":
        return "at most 6 characters", "at most 15 characters"
    return "1–3 words", "at most 8 words"


def system_prompt(s, source):
    """Depends only on the settings, so it forms a stable prefix for server-side prompt caching."""
    src, tgt = L.name(source), L.name(s.target)
    gloss_lim, note_lim = _limits(s.target)
    per100 = max(1, round(100 / s.density))
    example = EXAMPLE_OUT["zh" if L.base(s.target).startswith("zh") else "en"]
    culture = (
        f"\n* <note>: ONLY when the segment has an allusion, quotation, cultural/historical reference, "
        f"brand or public figure a foreign reader would miss. One short sentence in {tgt}, no spoilers. "
        f"Most segments have none." if s.culture else "")
    choose = (
        "Choose only expressions even a near-native C2 reader may not know: rare, literary, archaic, dialect or "
        "specialised words, uncommon idioms and slang. Skip everything a well-read native adult knows; tag "
        "what you choose C1 or C2." if s.level == "C2" else
        f"Choose expressions a {s.level} reader probably does not know: words above {s.level}, idioms, slang, "
        f"colloquialisms, fixed phrases, literary or irregular verb forms, tricky pronoun/clitic combinations. Also "
        f"include a few {s.level} items that are tricky in context. Skip words a {s.level} reader knows and "
        f"transparent cognates.")
    head = (f"[n] <{tgt} translation: faithful and natural; keep personal names and place names exactly as in the "
            f"original, never translate or transliterate them>" if s.translation else
            "[n]   (the number alone: no translation)")
    if not s.translation:
        example = "\n".join(re.sub(r"^(\[\d+\]).*", r"\1", x) for x in example.split("\n"))
    return f"""You annotate a {src} book for a learner of {src} at CEFR level {s.level} whose language is {tgt}. The result is read on an e-reader.
Input: numbered segments "[n] text" (plus optional context, which you must not annotate).
For EVERY segment, in order, output:
{head}
- <expression> | <gloss> | <CEFR> | <note> | <lemma>{culture}
Gloss lines (0 or more per segment):
- {choose} Never gloss personal or place names.
- expression: copied exactly from the segment (same spelling and apostrophes); a single word or a whole fixed phrase.
- gloss: the meaning in this context, in {tgt}, {gloss_lim}. It is printed above the word in small type.
- CEFR: the expression's own level as a learner's dictionary would tag it, the same whoever reads it: A1–A2 basic, B1–B2 everyday, C1 less common or formal, C2 rare, literary, archaic or specialised. Do not tag relative to this reader; literary texts have many C1/C2 items.
- note: optional, {note_lim}, in {tgt}: base form of irregular/rare verb forms, literal meaning, register (slang, vulgar), grammar point. Empty for simple words.
- lemma: dictionary form, only if different from the expression.
- Roughly {per100}–{per100 * 2} gloss lines per 100 words; fewer is fine.
Leave empty fields empty ("- word | gloss | B2 | |"). Output only these lines, nothing else.
Example (format only; your answer must be in {tgt}):
{EXAMPLE_IN}
→
{example}"""


def version(s):
    """Prompt version for the cache key."""
    return f"{PROMPT_VERSION}.c2v{C2_PROMPT_VERSION}" if s.level == "C2" else PROMPT_VERSION


def user_prompt(texts, context=""):
    lines = [f"Context (do not annotate): …{context[-200:]}"] if context else []
    lines += [f"[{i}] {t}" for i, t in enumerate(texts)]
    return "\n".join(lines)


def fix_quotes(s):
    """Replace straight double quotes left in Chinese/Japanese text with paired “ ”."""
    out, opening = [], True
    for ch in s:
        if ch == '"':
            out.append("“" if opening else "”")
            opening = not opening
        else:
            out.append(ch)
    return "".join(out)


_SEG = re.compile(r"^\s*\[(\d+)\]\s?(.*)$")
_GL = re.compile(r"^\s*[-–•]\s*(.*\|.*)$")
_CU = re.compile(r"^\s*\*\s*(.+)$")


def parse(text, target, culture=True, translation=True):
    """Line format -> {n: SegResult}. Tolerates blank lines, code fences and wrapped translations.
    translation=False: a bare "[n]" line counts as an answer; any translation text is discarded."""
    res, cur = {}, None
    cjk = L.is_cjk(target)
    for line in text.replace("\r", "").split("\n"):
        if not line.strip() or line.strip().startswith("```"):
            continue
        if m := _SEG.match(line):
            cur = res.setdefault(int(m.group(1)), SegResult())
            cur.tr = m.group(2).strip()
        elif cur is None:
            continue
        elif m := _GL.match(line):
            f = [x.strip() for x in m.group(1).split("|")] + ["", "", "", ""]
            if f[0] and f[1]:
                lv = LEVEL_RE.search(f[2])
                cur.gl.append(Gloss(f[0], f[1], lv.group(1).upper() if lv else "", f[3], f[4]))
        elif m := _CU.match(line):
            if culture:
                cur.cu = (cur.cu + " " + m.group(1).strip()).strip()
        elif not cur.gl and not cur.cu:
            cur.tr = (cur.tr + ("" if cjk else " ") + line.strip()).strip()
    if not translation:
        for r in res.values():
            r.tr = ""
    if cjk:
        for r in res.values():
            r.tr, r.cu = fix_quotes(r.tr), fix_quotes(r.cu)
            for g in r.gl:
                g.g, g.note = fix_quotes(g.g), fix_quotes(g.note)
    return res


# ---------- chapter guide ----------

def intro_prompt(s, source, chapter_text):
    tgt = L.name(s.target)
    return f"""Below is one full chapter of a {L.name(source)} book. Write a pre-reading guide in {tgt} for a {s.level} learner. Output exactly these lines:
S: <1–2 sentences on what happens; do not reveal the ending or twists>
P: <name as spelled in the text> — <who they are, a few words>   (2–5 lines: main people in this chapter; never translate names)
K: <keyword exactly as in the text> | <gloss in {tgt}, very short>   (3–5 lines: words above {s.level} that recur in this chapter and are needed to follow it)
State only what the text says. Output only these lines.

{chapter_text}

(End of chapter. Write the S/P/K lines in {tgt}, not in {L.name(source)}.)"""


def parse_intro(text, target):
    out = {"summary": "", "who": [], "kw": []}
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if line.startswith("S:"):
            out["summary"] = (out["summary"] + " " + line[2:].strip()).strip()
        elif line.startswith("P:"):
            out["who"].append(line[2:].strip())
        elif line.startswith("K:") and "|" in line:
            w, g = (x.strip() for x in line[2:].split("|", 1))
            if w and g:
                out["kw"].append({"w": w, "g": g})
    out["who"], out["kw"] = out["who"][:MAX_INTRO_ITEMS], out["kw"][:MAX_INTRO_ITEMS]
    if L.is_cjk(target):
        out["summary"] = fix_quotes(out["summary"])
        out["who"] = [fix_quotes(x) for x in out["who"]]
    return out
