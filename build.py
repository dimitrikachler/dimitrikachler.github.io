#!/usr/bin/env python3
"""Static site generator for dimitrikachler.github.io.

No dependencies beyond the Python standard library. Run `python3 build.py`
and the finished site appears in `_site/`.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
SITE_URL = "https://dimitrikachler.github.io"

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

class Markdown:
    """A small CommonMark subset: enough for research blogging."""

    def __init__(self) -> None:
        self.stash: list[str] = []

    def _keep(self, raw: str) -> str:
        """Park a literal string so later passes cannot touch it."""
        self.stash.append(raw)
        return f"\x00{len(self.stash) - 1}\x00"

    def _restore(self, text: str) -> str:
        def sub(m: re.Match) -> str:
            return self.stash[int(m.group(1))]
        # Nested placeholders are possible, so loop until stable.
        for _ in range(6):
            new = re.sub(r"\x00(\d+)\x00", sub, text)
            if new == text:
                break
            text = new
        return text

    # -- inline ------------------------------------------------------------

    def inline(self, text: str) -> str:
        # Math and code are protected before anything else touches them.
        text = re.sub(r"\$\$(.+?)\$\$",
                      lambda m: self._keep("$$" + html.escape(m.group(1)) + "$$"),
                      text, flags=re.S)
        text = re.sub(r"(?<![\w\\])\$(?!\s)([^\$\n]+?)(?<!\s)\$(?![\w])",
                      lambda m: self._keep("$" + html.escape(m.group(1)) + "$"),
                      text)
        text = re.sub(r"`([^`]+)`",
                      lambda m: self._keep("<code>" + html.escape(m.group(1)) + "</code>"),
                      text)

        text = html.escape(text, quote=False)

        # Images before links: the syntax differs only by the leading bang.
        text = re.sub(
            r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;([^&]*)&quot;)?\)",
            lambda m: self._keep(
                f'<img src="{html.escape(m.group(2), quote=True)}" '
                f'alt="{html.escape(m.group(1), quote=True)}" loading="lazy">'),
            text)
        text = re.sub(
            r"\[([^\]]+)\]\(([^)\s]+)\)",
            lambda m: self._keep(
                f'<a href="{html.escape(m.group(2), quote=True)}"'
                + (' target="_blank" rel="noopener"'
                   if m.group(2).startswith("http") else "")
                + f">{m.group(1)}</a>"),
            text)

        text = re.sub(r"\*\*\*(\S.*?\S|\S)\*\*\*", r"<strong><em>\1</em></strong>", text)
        text = re.sub(r"\*\*(\S.*?\S|\S)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", text)
        text = re.sub(r"(?<![\w\\])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w])", r"<em>\1</em>", text)
        text = re.sub(r"~~(\S.*?\S|\S)~~", r"<del>\1</del>", text)
        text = re.sub(r"  \n", "<br>\n", text)
        return text

    # -- block -------------------------------------------------------------

    def convert(self, text: str) -> str:
        # The stash is never cleared here: nested conversions share one list
        # with the outer document, so placeholder indices stay valid.
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text = text.replace("\r\n", "\n").replace("\t", "    ")
        lines = text.split("\n")
        out: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            # fenced code
            m = re.match(r"^(```|~~~)\s*([\w+-]*)\s*$", stripped)
            if m:
                fence, lang = m.group(1), m.group(2)
                i += 1
                buf: list[str] = []
                while i < len(lines) and not lines[i].strip().startswith(fence):
                    buf.append(lines[i])
                    i += 1
                i += 1
                cls = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
                body = html.escape("\n".join(buf))
                out.append(f'<pre><code{cls}>{body}</code></pre>')
                continue

            # display math
            if stripped.startswith("$$"):
                buf = [line]
                if stripped.count("$$") < 2:
                    i += 1
                    while i < len(lines) and "$$" not in lines[i]:
                        buf.append(lines[i])
                        i += 1
                    if i < len(lines):
                        buf.append(lines[i])
                i += 1
                out.append('<div class="math-block">'
                           + html.escape("\n".join(buf)) + "</div>")
                continue

            # raw html block
            if stripped.startswith("<") and not stripped.startswith("<http"):
                buf = []
                while i < len(lines) and lines[i].strip():
                    buf.append(lines[i])
                    i += 1
                out.append("\n".join(buf))
                continue

            # heading
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", stripped)
            if m:
                level = len(m.group(1))
                body = self.inline(m.group(2))
                slug = slugify(re.sub(r"<[^>]+>", "", self._restore(body)))
                out.append(
                    f'<h{level} id="{slug}">'
                    f'<a class="anchor" href="#{slug}" aria-hidden="true">#</a>'
                    f"{body}</h{level}>")
                i += 1
                continue

            # horizontal rule
            if re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$|^(_\s*){3,}$", stripped):
                out.append("<hr>")
                i += 1
                continue

            # blockquote
            if stripped.startswith(">"):
                buf = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                out.append("<blockquote>" + self.convert_nested("\n".join(buf))
                           + "</blockquote>")
                continue

            # lists
            if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
                ordered = bool(re.match(r"^\d+[.)]\s+", stripped))
                items: list[str] = []
                while i < len(lines):
                    cur = lines[i]
                    cs = cur.strip()
                    m = re.match(r"^[-*+]\s+(.*)$" if not ordered
                                 else r"^\d+[.)]\s+(.*)$", cs)
                    if m:
                        items.append(m.group(1))
                        i += 1
                        # continuation lines belonging to the same item
                        while (i < len(lines) and lines[i].strip()
                               and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i])
                               and not lines[i].strip().startswith(("#", ">", "```"))):
                            items[-1] += " " + lines[i].strip()
                            i += 1
                    elif not cs:
                        # blank line ends the list unless another item follows
                        j = i + 1
                        if (j < len(lines)
                                and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[j])):
                            i += 1
                            continue
                        break
                    else:
                        break
                tag = "ol" if ordered else "ul"
                body = "".join(f"<li>{self.inline(it)}</li>" for it in items)
                out.append(f"<{tag}>{body}</{tag}>")
                continue

            # paragraph
            buf = []
            while (i < len(lines) and lines[i].strip()
                   and not re.match(r"^\s*(#{1,6}\s|>|```|~~~|\$\$)", lines[i])
                   and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i])
                   and not re.match(r"^(\*\s*){3,}$|^(-\s*){3,}$", lines[i].strip())):
                buf.append(lines[i].strip())
                i += 1
            if buf:
                out.append("<p>" + self.inline(" ".join(buf)) + "</p>")
            else:
                i += 1

        return self._restore("\n".join(out))

    def convert_nested(self, text: str) -> str:
        """Convert a fragment while keeping the current placeholder stash."""
        saved = self.stash
        inner = Markdown()
        inner.stash = saved
        result = inner.convert(text)
        self.stash = inner.stash
        return result


def md(text: str) -> str:
    return Markdown().convert(text)


def md_inline(text: str) -> str:
    conv = Markdown()
    return conv._restore(conv.inline(text))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_-]+", "-", text) or "section"


def read_json(name: str):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def parse_front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw
    meta: dict = {}
    for line in parts[1].strip().split("\n"):
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
        elif value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value.strip("'\"")
    return meta, parts[2].lstrip("\n")


def pretty_date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            dt = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m":
            return f"{MONTHS[dt.month - 1]} {dt.year}"
        return f"{MONTHS[dt.month - 1]} {dt.day}, {dt.year}"
    return value


def rfc822(value: str) -> str:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def reading_time(text: str) -> str:
    words = len(re.findall(r"\w+", text))
    return f"{max(1, round(words / 220))} min read"


def highlight_self(author: str, me: str) -> str:
    return (f'<span class="me">{html.escape(author)}</span>'
            if author.strip() == me else html.escape(author))


ICONS = {
    "mail": '<path d="M2 5.5A2.5 2.5 0 0 1 4.5 3h11A2.5 2.5 0 0 1 18 5.5v9a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 2 14.5zM4.2 5l5.8 4.6L15.8 5z"/>',
    "github": '<path d="M10 1.5a8.5 8.5 0 0 0-2.7 16.6c.43.08.58-.19.58-.41v-1.6c-2.37.5-2.87-1.01-2.87-1.01-.39-.98-.95-1.24-.95-1.24-.77-.53.06-.52.06-.52.86.06 1.31.88 1.31.88.76 1.3 1.99.93 2.48.71.08-.55.3-.93.54-1.15-1.89-.21-3.88-.94-3.88-4.2 0-.93.33-1.69.88-2.29-.09-.21-.38-1.08.08-2.25 0 0 .71-.23 2.34.87a8.1 8.1 0 0 1 4.26 0c1.62-1.1 2.33-.87 2.33-.87.46 1.17.17 2.04.09 2.25.55.6.87 1.36.87 2.29 0 3.27-1.99 3.99-3.89 4.2.31.26.58.78.58 1.57v2.33c0 .22.15.49.59.41A8.5 8.5 0 0 0 10 1.5"/>',
    "scholar": '<path d="M10 2 1 7l9 5 7.3-4.06V13h1.7V7zM4.5 11v3.2c0 1.9 2.5 3.3 5.5 3.3s5.5-1.4 5.5-3.3V11l-5.5 3z"/>',
    "arxiv": '<path d="M3 3h3.2l3.9 6.1L14 3h3l-5.4 8L17 17h-3.2l-4-6.3L5.9 17H3l5.5-8z"/>',
    "linkedin": '<path d="M4.5 2.5a2 2 0 1 1 0 4 2 2 0 0 1 0-4M2.8 7.7h3.4V18H2.8zM8.4 7.7h3.25v1.42h.05c.45-.82 1.56-1.68 3.2-1.68 3.43 0 4.06 2.15 4.06 4.95V18h-3.4v-4.96c0-1.18-.02-2.7-1.7-2.7-1.7 0-1.96 1.29-1.96 2.62V18H8.4z"/>',
}


def icon(name: str) -> str:
    path = ICONS.get(name, ICONS["mail"])
    return (f'<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">'
            f"{path}</svg>")


# --------------------------------------------------------------------------
# templating
# --------------------------------------------------------------------------

TEMPLATE = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")


def render_page(site: dict, *, slug: str, title: str, body: str,
                depth: int = 0, description: str = "",
                active: str = "", wide: bool = False) -> str:
    prefix = "../" * depth
    nav_items = []
    for item in site["nav"]:
        is_active = item["href"].split("/")[0].replace(".html", "") == active
        href = prefix + item["href"]
        nav_items.append(
            f'<a class="nav-link{" is-active" if is_active else ""}" '
            f'href="{href}">{html.escape(item["label"])}</a>')

    link_items = []
    for item in site["links"]:
        href = item["href"]
        ext = ' target="_blank" rel="noopener"' if href.startswith("http") else ""
        link_items.append(
            f'<a class="ident-link" href="{html.escape(href, quote=True)}"{ext} '
            f'aria-label="{html.escape(item["label"], quote=True)}" '
            f'title="{html.escape(item["label"], quote=True)}">{icon(item["icon"])}</a>')

    full_title = title if slug == "index" else f"{title} · {site['name']}"
    values = {
        "title": html.escape(full_title, quote=True),
        "description": html.escape(description or site["tagline"], quote=True),
        "name": html.escape(site["name"]),
        "tagline": html.escape(site["tagline"]),
        "affiliation": md_inline(site["affiliation"]),
        "location": html.escape(site["location"]),
        "avatar": prefix + site["avatar"],
        "prefix": prefix,
        "nav": "\n".join(nav_items),
        "links": "\n".join(link_items),
        "body": body,
        "year": str(datetime.now().year),
        "main_class": "wide" if wide else "",
        "canonical": f"{SITE_URL}/{'' if slug == 'index' else slug}",
    }
    page = TEMPLATE
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------
# page builders
# --------------------------------------------------------------------------

def publication_card(pub: dict, me: str, *, compact: bool = False) -> str:
    authors = ", ".join(highlight_self(a, me) for a in pub["authors"])
    links = " ".join(
        f'<a class="pill-link" href="{html.escape(l["href"], quote=True)}" '
        f'target="_blank" rel="noopener">{html.escape(l["label"])}</a>'
        for l in pub.get("links", []))
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>'
                   for t in pub.get("tags", []))
    status = pub.get("status", "")
    badge = ""
    if status == "accepted":
        badge = '<span class="badge badge-accent">Accepted</span>'
    elif status == "preprint":
        badge = '<span class="badge">Preprint</span>'

    abstract = ""
    if not compact and pub.get("abstract"):
        abstract = f'<p class="pub-abstract">{html.escape(pub["abstract"])}</p>'

    return f"""<article class="pub accent-{pub.get('accent', 'lav')}">
  <div class="pub-year">{pub['year']}</div>
  <div class="pub-main">
    <h3 class="pub-title">{html.escape(pub['title'])}</h3>
    <p class="pub-authors">{authors}</p>
    <p class="pub-venue">{html.escape(pub['venue'])} {badge}</p>
    {abstract}
    <div class="pub-foot">{links}<span class="tags">{tags}</span></div>
  </div>
</article>"""


def build_home(site: dict, pubs: list, news: list, posts: list) -> str:
    about = md((ROOT / "content" / "about.md").read_text(encoding="utf-8"))

    hero = f"""
<header class="hero">
  <img class="avatar" src="{html.escape(site['avatar'], quote=True)}" alt=""
       width="96" height="96">
  <div class="hero-text">
    <h1 class="hero-name">{html.escape(site['name'])}</h1>
    <p class="hero-role">{html.escape(site['tagline'])}</p>
    <p class="hero-affil">{md_inline(site['affiliation'])}
      <span class="hero-sep">·</span> {html.escape(site['location'])}</p>
  </div>
</header>"""

    news_html = "".join(
        f'<li class="news-item accent-{n.get("accent", "lav")}">'
        f'<span class="news-date">{html.escape(pretty_date(n["date"]))}</span>'
        f'<span class="news-text">{md_inline(n["text"])}</span></li>'
        for n in news)

    selected = "".join(publication_card(p, site["name"], compact=True)
                       for p in pubs[:3])

    posts_html = ""
    if posts:
        rows = "".join(
            f'<li class="mini-post accent-{p["meta"].get("accent", "lav")}">'
            f'<a href="blog/{p["slug"]}.html">{html.escape(p["meta"]["title"])}</a>'
            f'<span class="mini-date">{html.escape(pretty_date(str(p["meta"]["date"])))}</span>'
            f"</li>" for p in posts[:3])
        posts_html = f"""
<section class="section">
  <div class="section-head"><h2>From the blog</h2>
    <a class="more" href="blog/index.html">all posts</a></div>
  <ul class="mini-posts">{rows}</ul>
</section>"""

    return f"""{hero}
<section class="section intro">
  <div class="prose">{about}</div>
</section>

<section class="section">
  <div class="section-head"><h2>Selected work</h2>
    <a class="more" href="publications.html">all publications</a></div>
  <div class="pub-list">{selected}</div>
</section>

<section class="section">
  <div class="section-head"><h2>News</h2></div>
  <ul class="news">{news_html}</ul>
</section>
{posts_html}
"""


def build_publications(site: dict, pubs: list) -> str:
    by_year: dict[int, list] = {}
    for pub in pubs:
        by_year.setdefault(pub["year"], []).append(pub)

    blocks = []
    for year in sorted(by_year, reverse=True):
        cards = "".join(publication_card(p, site["name"]) for p in by_year[year])
        blocks.append(f'<div class="year-group">'
                      f'<h2 class="year-head">{year}</h2>'
                      f'<div class="pub-list">{cards}</div></div>')

    return f"""
<header class="page-head">
  <h1>Publications</h1>
  <p class="lede">Peer-reviewed papers and preprints.</p>
</header>
{''.join(blocks)}
"""


def build_blog_index(site: dict, posts: list) -> str:
    if not posts:
        rows = '<p class="empty">No posts yet. Soon.</p>'
    else:
        rows = "".join(f"""
<article class="post-card accent-{p['meta'].get('accent', 'lav')}">
  <div class="post-meta">
    <time datetime="{html.escape(str(p['meta']['date']))}">
      {html.escape(pretty_date(str(p['meta']['date'])))}</time>
    <span class="dot">·</span><span>{p['reading_time']}</span>
  </div>
  <h2 class="post-title">
    <a href="{p['slug']}.html">{html.escape(p['meta']['title'])}</a></h2>
  <p class="post-summary">{html.escape(p['meta'].get('summary', ''))}</p>
  <div class="tags">{''.join(f'<span class="tag">{html.escape(t)}</span>'
                             for t in p['meta'].get('tags', []))}</div>
</article>""" for p in posts)

    return f"""
<header class="page-head">
  <h1>Blog</h1>
  <p class="lede">Notes from the PhD: things I read, things that broke, and
  things I wish someone had written down for me.</p>
  <p class="lede"><a class="pill-link" href="feed.xml">RSS</a></p>
</header>
<div class="post-list">{rows}</div>
"""


def build_post(site: dict, post: dict) -> str:
    meta = post["meta"]
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>'
                   for t in meta.get("tags", []))
    return f"""
<article class="post accent-{meta.get('accent', 'lav')}">
  <header class="post-head">
    <a class="back" href="index.html">← all posts</a>
    <h1>{html.escape(meta['title'])}</h1>
    <div class="post-meta">
      <time datetime="{html.escape(str(meta['date']))}">
        {html.escape(pretty_date(str(meta['date'])))}</time>
      <span class="dot">·</span><span>{post['reading_time']}</span>
    </div>
    <div class="tags">{tags}</div>
  </header>
  <div class="prose">{post['html']}</div>
</article>
"""


def build_drawings(site: dict, art: dict) -> str:
    items = "".join(f"""
<figure class="art-item accent-{a.get('accent', 'lav')}">
  <img src="{html.escape(a['src'], quote=True)}"
       alt="{html.escape(a.get('title', 'Drawing'), quote=True)}" loading="lazy">
  <figcaption><span class="art-title">{html.escape(a.get('title', ''))}</span>
    <span class="art-meta">{html.escape(a.get('meta', ''))}</span></figcaption>
</figure>""" for a in art.get("items", []))

    return f"""
<header class="page-head">
  <h1>Drawings</h1>
  <p class="lede">{md_inline(art.get('intro', ''))}</p>
</header>
<div class="art-grid">{items}</div>
"""


def build_feed(site: dict, posts: list) -> str:
    items = "".join(f"""  <item>
    <title>{html.escape(p['meta']['title'])}</title>
    <link>{SITE_URL}/blog/{p['slug']}.html</link>
    <guid>{SITE_URL}/blog/{p['slug']}.html</guid>
    <pubDate>{rfc822(str(p['meta']['date']))}</pubDate>
    <description>{html.escape(p['meta'].get('summary', ''))}</description>
  </item>
""" for p in posts)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>{html.escape(site['name'])} — Blog</title>
  <link>{SITE_URL}/blog/</link>
  <description>{html.escape(site['tagline'])}</description>
  <language>en</language>
{items}</channel></rss>
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def load_posts() -> list:
    posts = []
    post_dir = ROOT / "content" / "posts"
    for path in sorted(post_dir.glob("*.md")):
        meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
        if meta.get("draft"):
            continue
        if not meta.get("title"):
            print(f"  ! skipping {path.name}: no title in front matter")
            continue
        meta.setdefault("date", path.name[:10])
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
        posts.append({
            "slug": slug,
            "meta": meta,
            "html": md(body),
            "reading_time": reading_time(body),
        })
    posts.sort(key=lambda p: str(p["meta"]["date"]), reverse=True)
    return posts


def main() -> int:
    site = read_json("site.json")
    pubs = read_json("publications.json")
    news = read_json("news.json")
    art = read_json("art.json")
    posts = load_posts()

    pubs.sort(key=lambda p: (-p["year"], p["title"]))

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copytree(ROOT / "assets", OUT / "assets")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    for extra in ("CNAME", "robots.txt"):
        if (ROOT / extra).exists():
            shutil.copy(ROOT / extra, OUT / extra)

    write(OUT / "index.html", render_page(
        site, slug="index", title=f"{site['name']} — {site['tagline']}",
        body=build_home(site, pubs, news, posts), active="index",
        description=f"{site['name']}, {site['tagline']} at {site['affiliation']}."))

    write(OUT / "publications.html", render_page(
        site, slug="publications.html", title="Publications",
        body=build_publications(site, pubs), active="publications",
        description="Papers and preprints."))

    write(OUT / "drawings.html", render_page(
        site, slug="drawings.html", title="Drawings",
        body=build_drawings(site, art), active="drawings",
        description="Drawings and sketches.", wide=True))

    write(OUT / "blog" / "index.html", render_page(
        site, slug="blog/index.html", title="Blog",
        body=build_blog_index(site, posts), depth=1, active="blog",
        description="Notes from the PhD."))

    for post in posts:
        write(OUT / "blog" / f"{post['slug']}.html", render_page(
            site, slug=f"blog/{post['slug']}.html",
            title=post["meta"]["title"], body=build_post(site, post),
            depth=1, active="blog",
            description=post["meta"].get("summary", "")))

    write(OUT / "blog" / "feed.xml", build_feed(site, posts))

    write(OUT / "404.html", render_page(
        site, slug="404.html", title="Not found",
        body='<header class="page-head"><h1>404</h1>'
             '<p class="lede">That page does not exist. '
             '<a href="index.html">Back home</a>.</p></header>',
        active=""))

    pages = len(list(OUT.rglob("*.html")))
    print(f"  built {pages} pages, {len(posts)} posts, {len(pubs)} publications"
          f" → {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
