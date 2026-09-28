"""HTML preview: sample paragraphs with clickable ¶ notes. Level and density can be switched on the
page (every combination is pre-rendered, so switching costs nothing). Includes the cost estimate."""
import copy
import html
import json

from . import languages as L
from . import placement, render
from .config import DENSITY_NAMES, LEVELS, PRESETS

PAGE = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1f; --muted:#6b6b70; --line:#dddcd6; --card:#ffffff; --note:#f3f1ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#18181a; --fg:#e8e6e1; --muted:#9a9aa0; --line:#34343a; --card:#222226; --note:#2a2a2f; }} }}
body {{ background:var(--bg); color:var(--fg); font:17px/1.9 Georgia, "Songti SC", serif; margin:0; padding:0 16px 80px; }}
main {{ max-width:680px; margin:0 auto; }}
header {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:10px 0; z-index:2;
  font:14px/1.5 -apple-system, "PingFang SC", sans-serif; display:flex; gap:14px; flex-wrap:wrap; align-items:center; }}
select {{ font:inherit; }}
.stats {{ color:var(--muted); }}
table {{ border-collapse:collapse; font:13px/1.6 -apple-system, "PingFang SC", sans-serif; margin:16px 0; width:100%; }}
td {{ border-bottom:1px solid var(--line); padding:3px 8px 3px 0; vertical-align:top; }}
td:first-child {{ color:var(--muted); white-space:nowrap; }}
ruby.gbr {{ ruby-align:center; }} ruby.gbr rt {{ ruby-align:center; font-size:0.5em; color:var(--muted); border-bottom:1px solid var(--muted); padding-bottom:2px; }}
a.gb-nr {{ text-decoration:none!important; color:#888!important; cursor:pointer; font-size:1.2em; }}
.note {{ display:none; background:var(--note); border-radius:6px; padding:8px 12px; margin:4px 0 12px;
  font:15px/1.6 -apple-system, "PingFang SC", sans-serif; }}
.note.open {{ display:block; }}
.note p {{ margin:2px 0; }} .gb-gl, .gb-cu, .gb-kw {{ font-size:0.92em; }} .gb-n {{ color:var(--muted); }}
.variant {{ display:none; }} .variant.on {{ display:block; }}
h1 {{ font-size:1.3em; margin:18px 0 4px; }}
</style></head><body><main>
<h1>{title}</h1>
<table>{info}</table>
<header>
  <label>{t_level} <select id="lv">{lv_opts}</select></label>
  <label>{t_density} <select id="dn">{dn_opts}</select></label>
  <span class="stats" id="st"></span>
</header>
{variants}
</main>
<script>
const stats = {stats};
function show() {{
  const k = document.getElementById('lv').value + '-' + document.getElementById('dn').value;
  document.querySelectorAll('.variant').forEach(v => v.classList.toggle('on', v.dataset.k === k));
  const s = stats[k]; document.getElementById('st').textContent = s ? s : '';
}}
document.getElementById('lv').onchange = show; document.getElementById('dn').onchange = show;
document.addEventListener('click', e => {{
  const a = e.target.closest('a.gb-nr'); if (!a) return; e.preventDefault();
  const n = document.getElementById(a.dataset.v + '-' + a.getAttribute('href').split('#n-')[1]);
  if (n) n.classList.toggle('open');
}});
show();
</script></body></html>
"""

# Preview page labels (`preview --ui`; English by default like the rest of the tool)
TEXT = {
    "zh": {"level": "级别", "density": "密度", "stat": "{g} 个难词 / {r} 个上方小字（每百词 {gp} / {rp}）",
           "low": "稀", "normal": "中", "high": "密"},
    "en": {"level": "Level", "density": "Density", "stat": "{g} glosses / {r} above-word ({gp} / {rp} per 100 words)",
           "low": "low", "normal": "normal", "high": "high"},
}


def _variant(book, chapters, plans, outcome, s, lang, level, dname, vid):
    s2 = copy.copy(s)
    s2.level = level
    base = s.density if level == s.level else PRESETS[level]["density"]
    s2.density = base * DENSITY_NAMES[dname]
    placed = placement.choose(book, plans, outcome.results, s2, lang)
    label = L.ui(s.target)["culture"]
    parts = []
    for ch in chapters:
        by_block = render.segs_by_block(sg for sg in plans.get(ch.index, []) if sg.id in outcome.results)
        intro = outcome.intros.get(ch.index)
        if intro and intro.get("summary"):
            sid = f"gbc{ch.index}-intro"
            parts.append(f'<h2>{html.escape(ch.title)} <a class="gb-nr" data-v="{vid}" href="#n-{sid}"> ¶</a></h2>'
                         f'<div class="note" id="{vid}-{sid}">' +
                         "".join(f'<p class="{c}">{h}</p>' for c, h in render.intro_rows(intro, s.target)) + "</div>")
        for bi in sorted(by_block):
            h, done = render.block_html(book.blocks[bi].el, bi, by_block[bi], outcome, placed, s.translation)
            h = h.replace('class="gb-nr"', f'class="gb-nr" data-v="{vid}"')
            notes = "".join(f'<div class="note" id="{vid}-{sid}">' +
                            "".join(f'<p class="{c}">{x}</p>' for c, x in render.seg_rows(r, placed.get(seg.id, []), s.target, label, s.translation)) +
                            "</div>" for sid, seg, r in done)
            parts.append(h + notes)
    st = placement.stats(placed, {k: [sg for sg in v if sg.id in outcome.results] for k, v in plans.items()}, lang)
    return "".join(parts), st


def build(book, chapters, plans, outcome, s, lang, info_rows, title, ui_lang="en"):
    ui = TEXT.get(ui_lang, TEXT["en"])
    levels = LEVELS[LEVELS.index(s.level):]   # only upward: glosses were generated for the reader's level
    variants, stats = [], {}
    for lv in levels:
        for dn in DENSITY_NAMES:
            k = f"{lv}-{dn}"
            body, st = _variant(book, chapters, plans, outcome, s, lang, lv, dn, k.replace("-", ""))
            variants.append(f'<section class="variant" data-k="{k}">{body}</section>')
            stats[k] = ui["stat"].format(g=st["glosses"], r=st["rubies"], gp=st["gloss_per_100"], rp=st["ruby_per_100"])
    info = "".join(f"<tr><td>{html.escape(str(a))}</td><td>{html.escape(str(b))}</td></tr>" for a, b in info_rows)
    return PAGE.format(
        lang=ui_lang, title=html.escape(title), info=info, t_level=ui["level"], t_density=ui["density"],
        lv_opts="".join(f'<option value="{lv}"{" selected" if lv == s.level else ""}>{lv}</option>' for lv in levels),
        dn_opts="".join(f'<option value="{d}"{" selected" if d == "normal" else ""}>{ui[d]}</option>' for d in DENSITY_NAMES),
        variants="\n".join(variants), stats=json.dumps(stats, ensure_ascii=False))
