#!/usr/bin/env python3
"""Save every essay on a blog (default: nabeelqu.co) as its own EPUB.

Run it on your own computer, then drag the .epub files into the reMarkable
desktop app (or my.remarkable.com). Images are downloaded and embedded so the
books read fine offline.

    pip install requests beautifulsoup4 readability-lxml lxml_html_clean ebooklib
    python nabeelqu_to_epub.py --list     # see which pages it found
    python nabeelqu_to_epub.py            # write the EPUBs
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub
from readability import Document

DEFAULT_SITE = "https://nabeelqu.co/"
DEFAULT_AUTHOR = "Nabeel S. Qureshi"
USER_AGENT = "Mozilla/5.0 (personal offline reading; epub export)"

# Paths that are navigation rather than essays.
SKIP_PATH = re.compile(
    r"^/(about|contact|now|tags?|categor(y|ies)|page|feed|rss|archive|search|subscribe|privacy)(/|$)",
    re.I,
)
SKIP_EXT = re.compile(r"\.(xml|json|pdf|png|jpe?g|gif|svg|webp|css|js|ico|zip|mp[34])$", re.I)

CSS = """
body { font-family: serif; line-height: 1.5; margin: 0 4%; }
h1 { font-size: 1.6em; line-height: 1.2; margin: 0.5em 0 0.2em; }
p.source { font-size: 0.8em; color: #555; margin-bottom: 2em; }
img { max-width: 100%; height: auto; }
blockquote { margin: 1em 1.5em; font-style: italic; }
pre, code { font-family: monospace; font-size: 0.85em; white-space: pre-wrap; }
"""


def normalize(url):
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme, p.netloc.lower(), path, "", "", ""))


def is_candidate(url, host):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != host:
        return False
    return p.path not in ("", "/") and not SKIP_PATH.match(p.path) and not SKIP_EXT.search(p.path)


def fetch(session, url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r


def from_sitemap(session, site, host):
    urls, queue, seen = [], [urljoin(site, "/sitemap.xml")], set()
    while queue:
        sm = queue.pop()
        if sm in seen:
            continue
        seen.add(sm)
        try:
            soup = BeautifulSoup(fetch(session, sm).content, "xml")
        except Exception:
            continue
        for loc in soup.find_all("loc"):
            u = loc.get_text(strip=True)
            if u.endswith(".xml"):
                queue.append(u)
            elif is_candidate(u, host):
                urls.append(normalize(u))
    return urls


def from_homepage(session, site, host):
    soup = BeautifulSoup(fetch(session, site).text, "html.parser")
    for tag in soup.select("header, footer, nav"):
        tag.decompose()
    urls = [urljoin(site, a["href"]) for a in soup.find_all("a", href=True)]
    return [normalize(u) for u in urls if is_candidate(u, host)]


def discover(session, site):
    host = urlparse(site).netloc.lower().removeprefix("www.")
    # Homepage order is usually the author's own listing; sitemap catches the rest.
    found = from_homepage(session, site, host) + from_sitemap(session, site, host)
    return list(dict.fromkeys(found))


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "essay"


def build_epub(session, url, author):
    html = fetch(session, url).text
    doc = Document(html)
    title = doc.short_title().strip() or urlparse(url).path.strip("/")
    body = BeautifulSoup(doc.summary(html_partial=True), "html.parser")

    for tag in body.find_all(["script", "style", "iframe", "form", "noscript"]):
        tag.decompose()

    book = epub.EpubBook()
    book.set_identifier(url)
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    for i, img in enumerate(body.find_all("img")):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue
        try:
            r = fetch(session, urljoin(url, src))
        except Exception:
            img.decompose()
            continue
        ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
        ext = {"image/png": "png", "image/gif": "gif", "image/svg+xml": "svg",
               "image/webp": "webp"}.get(ctype, "jpg")
        name = f"images/img{i}.{ext}"
        book.add_item(epub.EpubItem(uid=f"img{i}", file_name=name, media_type=ctype, content=r.content))
        for attr in ("srcset", "data-src", "data-srcset", "loading"):
            img.attrs.pop(attr, None)
        img["src"] = name
        img["alt"] = img.get("alt", "")

    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(style)

    chapter = epub.EpubHtml(title=title, file_name="essay.xhtml", lang="en")
    chapter.content = (
        f"<h1>{escape(title)}</h1>"
        f'<p class="source">{escape(author)} · <a href="{escape(url)}">{escape(url)}</a></p>'
        f"{body}"
    )
    chapter.add_item(style)
    book.add_item(chapter)
    book.toc = [chapter]
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    return title, book


def escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=DEFAULT_SITE)
    ap.add_argument("--author", default=DEFAULT_AUTHOR)
    ap.add_argument("--out", default="nabeelqu-epubs", help="output folder")
    ap.add_argument("--list", action="store_true", help="only print the essay URLs found")
    ap.add_argument("--urls", help="text file of essay URLs (one per line) to use instead of auto-discovery")
    args = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    if args.urls:
        urls = [l.strip() for l in Path(args.urls).read_text().splitlines() if l.strip()]
    else:
        urls = discover(session, args.site)

    if args.list:
        print("\n".join(urls))
        print(f"\n{len(urls)} pages. Save any you want to skip/keep to a file and pass --urls.", file=sys.stderr)
        return

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failed = []
    for n, url in enumerate(urls, 1):
        try:
            title, book = build_epub(session, url, args.author)
            path = out / f"{slugify(title)}.epub"
            epub.write_epub(str(path), book)
            print(f"[{n}/{len(urls)}] {title}")
        except Exception as e:
            failed.append(url)
            print(f"[{n}/{len(urls)}] FAILED {url}: {e}", file=sys.stderr)
        time.sleep(1)  # be polite to the server

    print(f"\nWrote {len(urls) - len(failed)} EPUBs to {out.resolve()}")
    if failed:
        print("Failed:\n  " + "\n  ".join(failed), file=sys.stderr)


if __name__ == "__main__":
    main()
