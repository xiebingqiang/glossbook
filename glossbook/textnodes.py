"""Map character offsets in a text block (<p> etc.) to lxml text nodes, and insert or wrap
elements at given offsets.

The block's plain text is all its text nodes joined in document order. Text inside
<rt>/<rp>/script/style and inside our own inserted elements (class starting with "gb-") is
skipped, and so are footnote markers (see is_noteref) and print page numbers (is_pagebreak);
<br/> counts as one newline (a virtual node that nothing can be inserted into).
Inserting elements never changes the offsets of the original text, so edits can be applied
in any order.
"""
import re
from dataclasses import dataclass

SKIP_TAGS = {"rt", "rp", "script", "style"}
NO_NEST = {"a", "ruby"}  # never put an <a>/<ruby> inside one of these
_MARK = re.compile(r"[\[(]?(\d{1,3}|[*†‡]{1,3}|[a-z])[\])]?")
_PAGE = re.compile(r"[\[(|]?\s*(\d{1,4}|[ivxlcdm]{1,8})\s*[\])|]?", re.I)
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"


def local(tag):
    return tag.split("}")[-1].lower() if isinstance(tag, str) else ""


def is_ours(el):
    return (el.get("class") or "").startswith("gb-")


def is_noteref(el, before):
    """A footnote marker such as <sup>[1]</sup>, <a epub:type="noteref">3</a>, or a number glued
    to the previous word in its own element (Toschi,<span class="apice">4</span>). Markers are left
    out of the block text so the model never sees "word4"."""
    if "noteref" in (el.get(EPUB_TYPE) or ""):
        return True
    text = "".join(el.itertext()).strip()
    if not text or len(el) and local(el[0].tag) not in ("sup", "a", "span"):
        return False
    if not _MARK.fullmatch(text):
        return False
    tag = local(el.tag)
    if tag == "sup" or (tag == "a" and "#" in (el.get("href") or "")):
        return True
    return text.isdigit() and bool(before) and not before[-1].isspace() and not before[-1].isdigit()


def is_pagebreak(el):
    """A page number of the print edition: epub:type="pagebreak" / role="doc-pagebreak", or an element
    whose class or id mentions "page" and whose text is only a number (<span class="origpage">[12]</span>)."""
    if "pagebreak" in (el.get(EPUB_TYPE) or "") or el.get("role") == "doc-pagebreak":
        return True
    if "page" not in f"{el.get('class') or ''} {el.get('id') or ''}".lower():
        return False
    return bool(_PAGE.fullmatch("".join(el.itertext()).strip()))


@dataclass
class Node:
    owner: object   # element; None for the virtual newline of a <br>
    attr: str       # "text" (owner.text) or "tail" (owner.tail)
    start: int
    end: int


def collect(block):
    """Return (nodes, text)."""
    nodes, parts, pos = [], [], 0

    def add(owner, attr, s):
        nonlocal pos
        if s:
            nodes.append(Node(owner, attr, pos, pos + len(s)))
            parts.append(s)
            pos += len(s)

    def walk(el):
        add(el, "text", el.text)
        for child in el:
            if not isinstance(child.tag, str):      # comments, processing instructions
                add(child, "tail", child.tail)
                continue
            tag = local(child.tag)
            if tag == "br":
                add(None, "br", "\n")
            elif tag not in SKIP_TAGS and not is_ours(child) and not is_pagebreak(child) \
                    and not is_noteref(child, parts[-1] if parts else ""):
                walk(child)
            add(child, "tail", child.tail)

    walk(block)
    return nodes, "".join(parts)


def _container(node):
    return node.owner if node.attr == "text" else node.owner.getparent()


def _blocked_by(container, block):
    """The outermost <a>/<ruby> between container (inclusive) and block, or None."""
    hit, el = None, container
    while el is not None and el is not block:
        if local(el.tag) in NO_NEST:
            hit = el
        el = el.getparent()
    return hit


def _put(node, k, new_el, tail):
    """Place new_el at character k of node, followed by tail."""
    s = getattr(node.owner, node.attr)
    setattr(node.owner, node.attr, s[:k] or None)
    new_el.tail = tail
    if node.attr == "text":
        node.owner.insert(0, new_el)
    else:
        parent = node.owner.getparent()
        parent.insert(parent.index(node.owner) + 1, new_el)


def insert_at(block, offset, new_el):
    """Insert new_el at offset (used for ¶ links). Prefer the end of the node that ends at
    offset; if that is inside an <a>/<ruby>, put new_el right after that element instead."""
    nodes, _ = collect(block)
    real = [n for n in nodes if n.owner is not None]
    node = next((n for n in real if n.start < offset <= n.end), None) or \
        next((n for n in real if n.start <= offset <= n.end), None)
    if node is None:
        block.append(new_el)
        return
    blocker = _blocked_by(_container(node), block)
    if blocker is not None:
        new_el.tail = blocker.tail
        blocker.tail = None
        parent = blocker.getparent()
        parent.insert(parent.index(blocker) + 1, new_el)
        return
    k = offset - node.start
    s = getattr(node.owner, node.attr)
    _put(node, k, new_el, s[k:] or None)


def wrap(block, start, end, make_el):
    """Wrap text [start, end) in the element returned by make_el(text). Returns False (and does
    nothing) when the range spans several nodes or lies inside an <a>/<ruby>."""
    nodes, _ = collect(block)
    node = next((n for n in nodes if n.owner is not None and n.start <= start and end <= n.end), None)
    if node is None or _blocked_by(_container(node), block) is not None:
        return False
    s = getattr(node.owner, node.attr)
    a, b = start - node.start, end - node.start
    _put(node, a, make_el(s[a:b]), s[b:] or None)
    return True
