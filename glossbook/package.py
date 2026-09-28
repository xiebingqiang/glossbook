"""Write the EPUB: modified XHTML, note pages and CSS; add them to the OPF manifest/spine (note
pages linear="no"); upgrade EPUB2 to EPUB3; set the start location."""
import datetime as dt
import posixpath
import re
import uuid
import zipfile

from lxml import etree

from . import languages as L
from .epub import DC_NS, OPF_NS, OPS_NS, XHTML_NS, fix_entities, parse_xhtml
from .render import CSS, esc, notes_page
from .textnodes import local

NS = {"o": OPF_NS, "dc": DC_NS}


def rel(target, from_file):
    return posixpath.relpath(target, posixpath.dirname(from_file) or ".")


def _opf_dir(book):
    return posixpath.dirname(book.opf_path)


def _join(d, name):
    return posixpath.join(d, name) if d else name


def _add_css_link(tree, css_path, doc_path):
    root = tree.getroot()
    head = next((e for e in root if local(e.tag) == "head"), None)
    if head is None:
        return
    q = etree.QName(root).namespace
    link = etree.SubElement(head, f"{{{q}}}link" if q else "link")
    link.set("href", rel(css_path, doc_path))
    link.set("rel", "stylesheet")
    link.set("type", "text/css")


def _manifest_add(opf, href, id_, media, props=None):
    manifest = opf.find("o:manifest", NS)
    item = etree.SubElement(manifest, f"{{{OPF_NS}}}item", {"href": href, "id": id_, "media-type": media})
    if props:
        item.set("properties", props)


def _nav_xhtml(book, nav_path, start_path, toc_entries):
    items = "".join(f'<li><a href="{esc(rel(p, nav_path))}{"#" + a if a else ""}">{esc(label) or "·"}</a></li>'
                    for label, p, a in toc_entries if p in book.names)   # skip the source's broken links
    toc = f'<nav epub:type="toc" id="toc"><ol>{items}</ol></nav>' if items else ""
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
            f'<html xmlns="{XHTML_NS}" xmlns:epub="{OPS_NS}"><head><title>{esc(book.title)}</title></head><body>'
            f'{toc}<nav epub:type="landmarks" hidden=""><ol>'
            f'<li><a epub:type="bodymatter" href="{esc(rel(start_path, nav_path))}">Start</a></li>'
            '</ol></nav></body></html>\n')


def _add_landmarks(tree, nav_path, start_path):
    root = tree.getroot()
    if any(n.get(f"{{{OPS_NS}}}type") == "landmarks" for n in root.iter() if local(n.tag) == "nav"):
        return False
    body = next((e for e in root if local(e.tag) == "body"), None)
    if body is None:
        return False
    frag = etree.fromstring(
        f'<nav xmlns="{XHTML_NS}" xmlns:epub="{OPS_NS}" epub:type="landmarks" hidden=""><ol>'
        f'<li><a epub:type="bodymatter" href="{esc(rel(start_path, nav_path))}">Start</a></li></ol></nav>')
    body.append(frag)
    return True


def _metadata(book, opf, target, suffix):
    md = opf.find("o:metadata", NS)
    title = md.find("dc:title", NS)
    if title is not None and suffix not in (title.text or ""):
        title.text = f"{title.text or ''} {suffix}".strip()
    uid = opf.get("unique-identifier")
    ident = next((e for e in md.iterfind("dc:identifier", NS) if e.get("id") == uid), md.find("dc:identifier", NS))
    if ident is not None:     # new id so readers don't treat this as the original; stays a valid UUID
        new = str(uuid.uuid5(uuid.NAMESPACE_URL, f"glossbook:{target}:{(ident.text or '').strip()}"))
        ident.text = f"urn:uuid:{new}" if (ident.text or "").strip().startswith("urn:uuid:") else new
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    mod = next((m for m in md.iterfind("o:meta", NS) if m.get("property") == "dcterms:modified"), None)
    if mod is None:
        mod = etree.SubElement(md, f"{{{OPF_NS}}}meta", {"property": "dcterms:modified"})
    mod.text = now


def _guide_text(opf, start_href):
    guide = opf.find("o:guide", NS)
    if guide is None:
        guide = etree.SubElement(opf, f"{{{OPF_NS}}}guide")
    if not any(r.get("type") in ("text", "start") for r in guide):
        etree.SubElement(guide, f"{{{OPF_NS}}}reference", {"type": "text", "title": "Start", "href": start_href})


def _html5_docs(book, done):
    """When upgrading EPUB2 to EPUB3, untouched XHTML files also need the HTML5 doctype and numeric
    character references instead of HTML entities, or EPUB3 readers fail to parse them."""
    out = {}
    manifest = book.opf.find("o:manifest", NS)
    with zipfile.ZipFile(book.path) as z:
        for item in manifest.iterfind("o:item", NS):
            path = posixpath.normpath(_join(_opf_dir(book), item.get("href")))
            if item.get("media-type") != "application/xhtml+xml" or path in done or path not in book.names:
                continue
            text = z.read(path).decode("utf-8", errors="replace")
            new = re.sub(r"<!DOCTYPE[^>]*>", "<!DOCTYPE html>", fix_entities(text), count=1, flags=re.I)
            new = re.sub(r"<title>\s*</title>|<title\s*/>", f"<title>{esc(book.title) or 'x'}</title>", new, count=1)
            if new != text:
                out[path] = new.encode("utf-8")
    return out


def _epub2_metadata_cleanup(opf):
    """EPUB2 opf:scheme / opf:role / opf:file-as attributes and repeated dc:date are invalid in EPUB3."""
    md = opf.find("o:metadata", NS)
    for el in md:
        for a in [a for a in el.attrib if a.startswith(f"{{{OPF_NS}}}")]:
            del el.attrib[a]
    for extra in md.findall("dc:date", NS)[1:]:
        md.remove(extra)


def _synced_ncx(book, opf):
    """The NCX dtb:uid must match the new identifier. Returns the new NCX bytes, or None."""
    with zipfile.ZipFile(book.path) as z:
        ncx = etree.fromstring(z.read(book.ncx_path), etree.XMLParser(no_network=True, resolve_entities=False))
    uid = opf.find(f"o:metadata/dc:identifier[@id='{opf.get('unique-identifier')}']", NS)
    meta = next((m for m in ncx.iter() if local(m.tag) == "meta" and m.get("name") == "dtb:uid"), None)
    if uid is None or meta is None:
        return None
    meta.set("content", uid.text)
    return etree.tostring(ncx.getroottree(), xml_declaration=True, encoding="utf-8")


def _annotated_docs(book, notes, css_path, target, opf, files):
    """Note pages and the modified content documents."""
    spine = opf.find("o:spine", NS)
    for name, (di, part, asides) in notes.items():
        if not asides:
            continue
        path = _join(posixpath.dirname(book.docs[di].path), name)
        files[path] = notes_page("Notes", asides, L.base(target), rel(css_path, path)).encode("utf-8")
        nid = f"gb-notes-{di}" + (f"-{part}" if part else "")
        _manifest_add(opf, rel(path, book.opf_path), nid, "application/xhtml+xml")
        etree.SubElement(spine, f"{{{OPF_NS}}}itemref", {"idref": nid, "linear": "no"})
    for di in dict.fromkeys(di for di, _, _ in notes.values()):
        doc = book.docs[di]
        _add_css_link(doc.tree, css_path, doc.path)
        title = next((e for e in doc.tree.getroot().iter() if local(e.tag) == "title"), None)
        if title is not None and not (title.text or "").strip():
            title.text = book.title or "x"
        files[doc.path] = etree.tostring(doc.tree, xml_declaration=True, encoding="utf-8", doctype="<!DOCTYPE html>")


def write(book, out_path, notes, s, start_doc):
    """notes: {note page name: (doc index, part, [aside HTML])}; start_doc: doc index where the book
    opens (first selected chapter)."""
    opf, od = book.opf, _opf_dir(book)
    css_path = _join(od, "gb-style.css")
    files = {css_path: CSS.encode("utf-8")}
    _manifest_add(opf, rel(css_path, book.opf_path), "gb-css", "text/css")
    _annotated_docs(book, notes, css_path, s.target, opf, files)

    start_path = book.docs[start_doc].path
    upgrading = not book.version.startswith("3")
    if upgrading or not book.nav_path:
        nav_path = _join(od, "gb-nav.xhtml")
        files[nav_path] = _nav_xhtml(book, nav_path, start_path, book.toc).encode("utf-8")
        _manifest_add(opf, rel(nav_path, book.opf_path), "gb-nav", "application/xhtml+xml", "nav")
        opf.set("version", "3.0")
    else:
        with zipfile.ZipFile(book.path) as z:
            tree = parse_xhtml(z.read(book.nav_path))
        if _add_landmarks(tree, book.nav_path, start_path):
            files[book.nav_path] = etree.tostring(tree, xml_declaration=True, encoding="utf-8")
    _metadata(book, opf, L.base(s.target), L.title_suffix(s.target))
    if upgrading:
        _epub2_metadata_cleanup(opf)
    if book.ncx_path in book.names:
        ncx = _synced_ncx(book, opf)
        if ncx:
            files[book.ncx_path] = ncx
    _guide_text(opf, rel(start_path, book.opf_path))
    files[book.opf_path] = etree.tostring(opf, xml_declaration=True, encoding="utf-8")
    if upgrading:
        files.update(_html5_docs(book, files))

    with zipfile.ZipFile(book.path) as src, zipfile.ZipFile(out_path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for info in src.infolist():
            if info.filename == "mimetype" or info.filename in files:
                continue
            z.writestr(info, src.read(info.filename), compress_type=zipfile.ZIP_DEFLATED)
        for path, data in files.items():
            z.writestr(path, data, compress_type=zipfile.ZIP_DEFLATED)
