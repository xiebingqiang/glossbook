"""Save the paragraphs of a Wikisource page as plain text: python3 wikisource.py HOST PAGE OUT.txt"""
import json
import sys
import urllib.parse
import urllib.request

from lxml import html

DROP = ('//*[self::sup or self::style or contains(@class,"ws-noexport") or contains(@class,"reference") '
        'or contains(@class,"pagenum")]')

host, page, out = sys.argv[1:4]
url = f"https://{host}/w/api.php?action=parse&format=json&prop=text&redirects=1&page=" + urllib.parse.quote(page)
req = urllib.request.Request(url, headers={"User-Agent": "glossbook-sample/0.1"})
tree = html.fromstring(json.load(urllib.request.urlopen(req))["parse"]["text"]["*"])
for bad in tree.xpath(DROP):
    bad.drop_tree()
paras = [" ".join(p.text_content().split()) for p in tree.xpath("//p")]
with open(out, "w") as f:
    f.write("\n\n".join(p for p in paras if p))
