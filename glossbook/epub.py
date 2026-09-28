"""Read an EPUB: container -> OPF -> spine and table of contents; detect DRM; split the body text
into text blocks. Chapters are built from these in chapters.py."""
import html.entities
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from urllib.parse import unquote

from lxml import etree

from .textnodes import collect, local

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
OPS_NS = "http://www.idpf.org/2007/ops"
XHTML_NS = "http://www.w3.org/1999/xhtml"
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}

BLOCK_TAGS = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt",
              "td", "th", "figcaption", "section", "article", "aside", "header", "footer",
              "ul", "ol", "dl", "table", "tr", "tbody", "thead", "figure", "main", "nav", "pre",
              "hr", "body"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_CONTAINERS = {"nav", "pre", "table", "script", "style", "svg", "math"}
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


class EpubError(Exception):
    pass


@dataclass
class Doc:
    path: str          # full path inside the zip
    idref: str
    linear: bool
    tree: object = None
    error: str = ""


@dataclass
class Block:
    doc: int           # index into Book.docs
    el: object
    heading: bool
    text: str
    order: int         # document order within its file


@dataclass
class Book:
    path: str
    names: list
    opf_path: str
    opf: object
    version: str
    lang: str
    title: str
    docs: list
    toc: list = field(default_factory=list)       # [(label, path, anchor)]
    blocks: list = field(default_factory=list)
    chapters: list = field(default_factory=list)  # filled in by chapters.make_chapters
    nav_path: str | None = None
    ncx_path: str | None = None


def fix_entities(raw):
    """Turn HTML entities that XHTML doesn't declare (&nbsp; &mdash; ...) into numeric references;
    otherwise XML parsing fails."""
    def rep(m):
        name = m.group(1)
        if name in _XML_ENTITIES or name not in html.entities.name2codepoint:
            return m.group(0)
        return f"&#{html.entities.name2codepoint[name]};"
    return re.sub(r"&([A-Za-z][A-Za-z0-9]*);", rep, raw)


def parse_xhtml(raw_bytes):
    text = raw_bytes.decode("utf-8", errors="replace").lstrip("﻿")
    text = re.sub(r"^<\?xml[^>]*\?>", "", text.lstrip())
    text = fix_entities(text)
    if "xmlns:epub" not in text[:2000]:     # so inserted epub:type attributes use the epub: prefix
        text = re.sub(r"<html\b", f'<html xmlns:epub="{OPS_NS}"', text, count=1)
    data = text.encode("utf-8")
    try:
        return etree.ElementTree(etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True)))
    except etree.XMLSyntaxError:
        root = etree.fromstring(data, etree.XMLParser(recover=True, no_network=True))
        if root is None:
            raise
        return etree.ElementTree(root)


def check_drm(z):
    names = set(z.namelist())
    if "META-INF/rights.xml" in names:
        raise EpubError("this EPUB is DRM-protected (META-INF/rights.xml) and cannot be processed")
    if "META-INF/encryption.xml" in names:
        enc = etree.fromstring(z.read("META-INF/encryption.xml"))
        algs = {m.get("Algorithm") for m in enc.iter() if local(m.tag) == "encryptionmethod"}
        if algs - FONT_OBFUSCATION:
            raise EpubError("this EPUB is encrypted (DRM) and cannot be processed")


def _opf_path(z):
    try:
        c = etree.fromstring(z.read("META-INF/container.xml"))
    except KeyError:
        opfs = [n for n in z.namelist() if n.endswith(".opf")]
        if not opfs:
            raise EpubError("no container.xml and no .opf file: not a valid EPUB") from None
        return opfs[0]
    rf = next((e for e in c.iter() if local(e.tag) == "rootfile"), None)
    if rf is None:
        raise EpubError("container.xml has no rootfile")
    return rf.get("full-path")


def resolve(base_path, href):
    href = unquote(href.split("#")[0])
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_path), href)) if href else base_path


def _anchor(href):
    return href.split("#", 1)[1] if "#" in href else None


def _label(el):
    return " ".join("".join(el.itertext()).split())


def read_toc(z, book):
    """[(label, path, anchor)] from the EPUB3 nav document, or from the NCX as a fallback."""
    entries = []
    if book.nav_path in book.names:
        root = parse_xhtml(z.read(book.nav_path)).getroot()
        nav = next((n for n in root.iter() if local(n.tag) == "nav" and n.get(f"{{{OPS_NS}}}type") == "toc"), None)
        if nav is not None:
            for a in nav.iter():
                if local(a.tag) == "a" and a.get("href"):
                    entries.append((_label(a), resolve(book.nav_path, a.get("href")), _anchor(a.get("href"))))
    if not entries and book.ncx_path in book.names:
        ncx = etree.fromstring(z.read(book.ncx_path))
        for point in ncx.iter(f"{{{NCX_NS}}}navPoint"):
            text = point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
            content = point.find(f"{{{NCX_NS}}}content")
            if content is not None and content.get("src"):
                src = content.get("src")
                entries.append((_label(text) if text is not None else "", resolve(book.ncx_path, src), _anchor(src)))
    return entries


def load(path):
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, FileNotFoundError) as e:
        raise EpubError(f"cannot open {path}: {e}") from e
    with z:
        check_drm(z)
        opf_path = _opf_path(z)
        try:
            opf = etree.fromstring(z.read(opf_path))
        except KeyError:
            raise EpubError(f"{opf_path} not found") from None
        ns = {"o": OPF_NS, "dc": DC_NS}
        manifest = {i.get("id"): i for i in opf.iterfind(".//o:manifest/o:item", ns)}
        lang_el, title_el = opf.find(".//dc:language", ns), opf.find(".//dc:title", ns)
        book = Book(path=str(path), names=z.namelist(), opf_path=opf_path, opf=opf,
                    version=opf.get("version", "2.0"),
                    lang=(lang_el.text or "").strip() if lang_el is not None else "",
                    title=(title_el.text or "").strip() if title_el is not None else "", docs=[])
        for item in manifest.values():
            if "nav" in (item.get("properties") or "").split():
                book.nav_path = resolve(opf_path, item.get("href"))
            if item.get("media-type") == "application/x-dtbncx+xml":
                book.ncx_path = resolve(opf_path, item.get("href"))
        for ref in opf.iterfind(".//o:spine/o:itemref", ns):
            item = manifest.get(ref.get("idref"))
            if item is None or "html" not in (item.get("media-type") or ""):
                continue
            doc = Doc(resolve(opf_path, item.get("href")), ref.get("idref"), ref.get("linear") != "no")
            try:
                doc.tree = parse_xhtml(z.read(doc.path))
            except (KeyError, etree.XMLSyntaxError) as e:
                doc.error = str(e)
            book.docs.append(doc)
        book.toc = read_toc(z, book)
    _collect_blocks(book)
    return book


def _is_container(el, tag):
    """A block-level element that contains other block-level elements (we descend into it)."""
    return tag in BLOCK_TAGS and tag != "body" and any(
        local(d.tag) in BLOCK_TAGS for d in el.iterdescendants() if isinstance(d.tag, str))


def _collect_blocks(book):
    for di, doc in enumerate(book.docs):
        if doc.tree is None or not doc.linear or doc.path == book.nav_path:
            continue
        body = next((e for e in doc.tree.getroot() if local(e.tag) == "body"), None)
        if body is None:
            continue
        order = {el: i for i, el in enumerate(doc.tree.getroot().iter())}

        def walk(el, di=di, order=order):
            for child in el:
                if not isinstance(child.tag, str):
                    continue
                tag = local(child.tag)
                if tag in SKIP_CONTAINERS:
                    continue
                if tag in BLOCK_TAGS and not _is_container(child, tag):
                    _, text = collect(child)
                    if any(c.isalnum() for c in text):
                        book.blocks.append(Block(di, child, tag in HEADINGS, text, order[child]))
                else:
                    walk(child)
        walk(body)
