
#!/usr/bin/env python3
"""
Analytics4 Blog Migration
Original website: https://analytics4.online/

Imports Website Builder / SitePro blog articles into
static HTML pages for GitHub Pages.

Run:
    python migrate_blog.py --pages 12 --download-assets

Generated:
    Blog/index.html
    Blog/<slug>/index.html
    assets/blog/<images>
    content/blog_manifest.json

All imported pages require review before the domain migration.
"""

import argparse
import copy
import hashlib
import html
import json
import re
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


BASE = "https://analytics4.online/"
ROOT = Path(__file__).resolve().parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Analytics4BlogMigration/3.0)"
}

HOSTS = {
    "analytics4.online",
    "www.analytics4.online"
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"
}

EXCLUDED_SLUGS = {
    "blog",
    "page",
    "category",
    "tag",
    "index",
    "google-ads",
    "referenze",
    "hot-news"
}


# --------------------------------------------------
# NETWORK
# --------------------------------------------------

def fetch(session, url):
    response = session.get(
        url,
        headers=HEADERS,
        timeout=35
    )
    response.raise_for_status()
    return response


def normalize_url(url, base=BASE):
    absolute = urljoin(base, url)
    parsed = urlparse(absolute)

    if parsed.scheme not in ("http", "https"):
        return None

    if parsed.netloc.lower() not in HOSTS:
        return None

    return urlunparse((
        "https",
        "analytics4.online",
        parsed.path,
        "",
        "",
        ""
    ))


# --------------------------------------------------
# DISCOVER BLOG ARTICLES
# --------------------------------------------------

def discover(soup, page_url):
    found = set()

    for anchor in soup.select("a[href]"):
        url = normalize_url(anchor["href"], page_url)

        if not url:
            continue

        path = urlparse(url).path

        if not re.fullmatch(
            r"/Blog/[^/]+/?",
            path,
            flags=re.IGNORECASE
        ):
            continue

        slug = path.strip("/").split("/")[-1]

        if slug.lower() in EXCLUDED_SLUGS:
            continue

        found.add(url.rstrip("/") + "/")

    return found


# --------------------------------------------------
# WEBSITE BUILDER ARTICLE EXTRACTION
# --------------------------------------------------

def article_container(soup):
    """
    Actual structure verified from original Analytics4 HTML:

    [data-plugin="Blog"]
      .wb-blog
        [itemtype="https://schema.org/BlogPosting"]
        div[style*="overflow: hidden"]
          h1
          p
          images
          ...
    """

    for plugin in soup.select('[data-plugin="Blog"]'):
        for blog in plugin.select(".wb-blog"):

            metadata = blog.select_one(
                '[itemtype="https://schema.org/BlogPosting"]'
            )

            if metadata is None:
                continue

            for child in blog.find_all(
                "div",
                recursive=False
            ):
                style = re.sub(
                    r"\s+",
                    "",
                    child.get("style", "").lower()
                )

                if "overflow:hidden" not in style:
                    continue

                if len(
                    child.get_text(" ", strip=True)
                ) >= 180:
                    return child, metadata

    # Fallback for other blog layouts.
    selectors = [
        '[itemprop="articleBody"]',
        ".blog-post-content",
        ".post-content",
        ".wb_blog_post_content",
        "article"
    ]

    for selector in selectors:
        for element in soup.select(selector):
            if len(
                element.get_text(" ", strip=True)
            ) >= 180:
                return element, None

    return None, None


def meta_value(element, selector, attribute="content"):
    if element is None:
        return ""

    node = element.select_one(selector)

    if node is None:
        return ""

    return node.get(attribute, "").strip()


def clean_content(element):
    content = BeautifulSoup(
        str(element),
        "html.parser"
    )

    for node in list(content.select(
        "script, style, iframe, form, nav, "
        "footer, header, button, noscript"
    )):
        node.decompose()

    for node in content.find_all(True):
        for attribute in list(node.attrs):

            if attribute.lower().startswith("on"):
                del node[attribute]

            elif attribute.lower() in {
                "contenteditable"
            }:
                del node[attribute]

        # Remove embedded editor controls.
        if node.has_attr("data-_"):
            del node["data-_"]

    return content


# --------------------------------------------------
# IMAGES
# --------------------------------------------------

def download_image(session, image_url):
    try:
        response = fetch(session, image_url)

        content_type = response.headers.get(
            "Content-Type", ""
        ).split(";")[0].lower()

        if not content_type.startswith("image/"):
            raise ValueError(
                "Downloaded resource is not an image"
            )

        extension = Path(
            urlparse(image_url).path
        ).suffix.lower()

        if extension not in IMAGE_EXTENSIONS:
            extension = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/svg+xml": ".svg"
            }.get(content_type, ".jpg")

        filename = (
            hashlib.sha256(
                image_url.encode("utf-8")
            ).hexdigest()[:20]
            + extension
        )

        folder = ROOT / "assets" / "blog"
        folder.mkdir(
            parents=True,
            exist_ok=True
        )

        destination = folder / filename

        if not destination.exists():
            destination.write_bytes(
                response.content
            )

        return "../../assets/blog/" + filename

    except Exception as exc:
        print(
            "IMAGE WARNING:",
            image_url,
            str(exc),
            flush=True
        )
        return image_url


def process_images(
    session,
    content,
    source_url,
    download_assets
):
    for image in content.select("img"):

        original = (
            image.get("data-src")
            or image.get("data-original")
            or image.get("src")
        )

        if not original:
            continue

        absolute = urljoin(
            BASE,
            original
        )

        if not absolute.startswith(
            ("https://", "http://")
        ):
            continue

        if download_assets:
            image["src"] = download_image(
                session,
                absolute
            )
        else:
            image["src"] = absolute

        # Avoid stale source-site responsive images.
        image.attrs.pop("srcset", None)
        image.attrs.pop("data-srcset", None)


# --------------------------------------------------
# EXTRACT COMPLETE ARTICLE
# --------------------------------------------------

def extract_article(
    session,
    url,
    download_assets
):
    response = fetch(session, url)

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    body, metadata = article_container(soup)

    if body is None:
        raise ValueError(
            "Article body not identified safely"
        )

    # Use the structured-data title first.
    title = meta_value(
        metadata,
        '[itemprop="headline"]'
    )

    if not title:
        heading = body.select_one("h1, h2")

        if heading:
            title = heading.get_text(
                " ",
                strip=True
            )

    if not title:
        og_title = soup.select_one(
            'meta[property="og:title"]'
        )
        if og_title:
            title = og_title.get(
                "content", ""
            ).strip()

    if not title or len(title) < 5:
        raise ValueError(
            "Article title missing"
        )

    content = clean_content(body)

    text_length = len(
        content.get_text(
            " ",
            strip=True
        )
    )

    if text_length < 180:
        raise ValueError(
            "Article content too short"
        )

    # The original website uses a root <base href>.
    # Resolve relative links against the website root.
    for link in content.select("a[href]"):

        href = link.get("href", "").strip()

        if href.lower().startswith(
            ("javascript:", "data:")
        ):
            del link["href"]

        elif href.startswith("#"):
            continue

        else:
            link["href"] = urljoin(
                BASE,
                href
            )

    process_images(
        session,
        content,
        url,
        download_assets
    )

    slug = urlparse(
        url
    ).path.strip("/").split("/")[-1]

    description_tag = soup.select_one(
        'meta[name="description"]'
    )

    description = (
        description_tag.get("content", "")
        if description_tag
        else ""
    )

    published = meta_value(
        metadata,
        '[itemprop="datePublished"]'
    )

    modified = meta_value(
        metadata,
        '[itemprop="dateModified"]'
    )

    if not published:
        published_tag = soup.select_one(
            'meta[property="article:published_time"],'
            'time[datetime]'
        )

        if published_tag:
            published = (
                published_tag.get("content")
                or published_tag.get("datetime")
                or ""
            )

    language = (
        soup.html.get("lang", "it")
        if soup.html
        else "it"
    )

    # Featured image from schema.org or Open Graph.
    featured_image = ""

    if metadata:
        image_tag = metadata.select_one(
            '[itemprop="image"]'
        )

        if image_tag:
            featured_image = (
                image_tag.get("href")
                or image_tag.get("content")
                or image_tag.get("src")
                or ""
            )

    if not featured_image:
        og_image = soup.select_one(
            'meta[property="og:image"]'
        )

        if og_image:
            featured_image = og_image.get(
                "content", ""
            )

    if featured_image:
        featured_image = urljoin(
            BASE,
            featured_image
        )

    local_featured_image = featured_image

    if featured_image and download_assets:
        local_featured_image = download_image(
            session,
            featured_image
        )

    # Preserve language alternative URLs in manifest.
    alternates = {}

    for link in soup.select(
        'link[rel="alternate"][hreflang]'
    ):
        lang = link.get("hreflang")
        href = link.get("href")

        if lang and href:
            alternates[lang] = urljoin(
                BASE,
                href
            )

    return {
        "slug": slug,
        "source_url": url,
        "title": title,
        "description": description,
        "date": published,
        "modified": modified,
        "language": language,
        "featured_image": local_featured_image,
        "original_featured_image": featured_image,
        "alternates": alternates,
        "html": str(content),
        "text_length": text_length,
        "status": "needs_review"
    }


# --------------------------------------------------
# HTML TEMPLATE
# --------------------------------------------------

def make_page(
    title,
    body,
    depth,
    description="",
    language="it"
):
    root = "../" * depth

    meta_description = ""

    if description:
        meta_description = (
            '<meta name="description" content="'
            + html.escape(
                description,
                quote=True
            )
            + '">'
        )

    return f"""<!DOCTYPE html>
<html lang="{html.escape(language, quote=True)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>{html.escape(title)} | Analytics 4</title>
{meta_description}
<link rel="stylesheet" href="{root}assets/blog.css">
<style>
body {{
    margin: 0;
    background: #101010;
    color: #f4f4f4;
    font-family: Arial, sans-serif;
    line-height: 1.7;
}}
header {{
    background: #080808;
    border-bottom: 1px solid #333;
    padding: 22px 6%;
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 15px;
}}
header a, nav a {{
    color: white;
    text-decoration: none;
}}
.logo {{
    font-size: 24px;
    font-weight: bold;
}}
.logo b {{
    color: #ff7900;
}}
nav {{
    display: flex;
    gap: 22px;
}}
main {{
    max-width: 950px;
    margin: 45px auto;
    padding: 0 22px;
}}
article {{
    overflow-wrap: anywhere;
}}
article img {{
    max-width: 100%;
    height: auto;
    border-radius: 10px;
}}
article a {{
    color: #ff9500;
}}
h1, h2, h3 {{
    line-height: 1.3;
}}
h1 {{
    font-size: clamp(30px, 5vw, 44px);
}}
.post {{
    display: block;
    padding: 24px;
    margin: 15px 0;
    border: 1px solid #333;
    border-radius: 12px;
    color: white;
    text-decoration: none;
    background: #191919;
}}
.post:hover {{
    border-color: #ff7900;
}}
.post img {{
    width: 100%;
    max-height: 260px;
    object-fit: cover;
    border-radius: 8px;
}}
.post h2 {{
    color: #ff9500;
}}
.date {{
    color: #aaa;
    font-size: 14px;
}}
footer {{
    border-top: 1px solid #333;
    text-align: center;
    padding: 30px;
    color: #aaa;
}}
</style>
</head>
<body>
<header>
<a class="logo" href="{root}">Analytics <b>4</b></a>
<nav>
<a href="{root}">Home</a>
<a href="{root}Blog/">Blog</a>
<a href="mailto:stefano@analytics4.online">Contact</a>
</nav>
</header>
<main>
{body}
</main>
<footer>
© Analytics 4
</footer>
</body>
</html>"""


# --------------------------------------------------
# GENERATE ARTICLE PAGES
# --------------------------------------------------

def generate_article(post):
    destination = (
        ROOT
        / "Blog"
        / post["slug"]
        / "index.html"
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    date_html = ""

    if post["date"]:
        date_html = (
            '<p class="date">'
            + html.escape(post["date"][:10])
            + "</p>"
        )

    # Keep article's original internal headings.
    # Add a title only if its body has no heading.
    article_html = post["html"]

    parsed = BeautifulSoup(
        article_html,
        "html.parser"
    )

    if not parsed.select_one("h1"):
        article_html = (
            "<h1>"
            + html.escape(post["title"])
            + "</h1>"
            + article_html
        )

    body = f"""
<p><a href="../">← Back to Blog</a></p>
{date_html}
<article>
{article_html}
</article>
"""

    destination.write_text(
        make_page(
            post["title"],
            body,
            2,
            post["description"],
            post["language"]
        ),
        encoding="utf-8"
    )


# --------------------------------------------------
# GENERATE BLOG ARCHIVE
# --------------------------------------------------

def generate_archive(posts):
    cards = []

    for post in posts:

        image_html = ""

        if post["featured_image"]:
            image_html = (
                '<img src="'
                + html.escape(
                    post["featured_image"],
                    quote=True
                )
                + '" alt="'
                + html.escape(
                    post["title"],
                    quote=True
                )
                + '">'
            )

        date_html = ""

        if post["date"]:
            date_html = (
                '<p class="date">'
                + html.escape(
                    post["date"][:10]
                )
                + "</p>"
            )

        card = f"""
<a class="post" href="{html.escape(post['slug'], quote=True)}/">
{image_html}
{date_html}
<h2>{html.escape(post['title'])}</h2>
<p>{html.escape(post['description'][:220])}</p>
</a>
"""
        cards.append(card)

    body = """
<h1>Blog & Insights</h1>
<p>Articoli e approfondimenti di Analytics 4.</p>
<section class="posts">
""" + "\n".join(cards) + """
</section>
"""

    destination = ROOT / "Blog" / "index.html"

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    destination.write_text(
        make_page(
            "Blog",
            body,
            1
        ),
        encoding="utf-8"
    )


# --------------------------------------------------
# MAIN MIGRATION
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--pages",
        type=int,
        default=12
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.8
    )

    parser.add_argument(
        "--download-assets",
        action="store_true"
    )

    args = parser.parse_args()

    session = requests.Session()

    found = set()
    errors = []

    print(
        "Starting Analytics4 blog migration...",
        flush=True
    )

    # Discover articles from archive pagination.
    for number in range(1, args.pages + 1):

        if number == 1:
            candidates = [
                BASE + "Blog/"
            ]

        else:
            candidates = [
                BASE + f"Blog/?bpage={number}",
                BASE + f"Blog/?bcpp=4&bpage={number}"
            ]

        for url in candidates:
            try:
                response = fetch(
                    session,
                    url
                )

                soup = BeautifulSoup(
                    response.text,
                    "html.parser"
                )

                found.update(
                    discover(soup, url)
                )

            except Exception as exc:
                errors.append({
                    "url": url,
                    "error": str(exc),
                    "type": "archive"
                })

                print(
                    "ARCHIVE WARNING",
                    url,
                    exc,
                    flush=True
                )

            time.sleep(args.delay)

    print(
        "Discovered article URLs:",
        len(found),
        flush=True
    )

    posts = []

    # Extract every discovered article.
    for index, url in enumerate(
        sorted(found),
        start=1
    ):
        print(
            f"[{index}/{len(found)}] Importing:",
            url,
            flush=True
        )

        try:
            post = extract_article(
                session,
                url,
                args.download_assets
            )

            posts.append(post)

            print(
                "EXTRACTED:",
                post["title"],
                flush=True
            )

        except Exception as exc:
            errors.append({
                "url": url,
                "error": str(exc),
                "type": "article"
            })

            print(
                "REVIEW REQUIRED:",
                url,
                str(exc),
                flush=True
            )

        time.sleep(args.delay)

    # Prefer newest articles first when dates exist.
    posts.sort(
        key=lambda post: post.get("date", ""),
        reverse=True
    )

    # Always write an import report.
    report = {
        "source": BASE + "Blog/",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "discovered": len(found),
        "exported": len(posts),
        "failed_articles": len(found) - len(posts),
        "posts": posts,
        "errors": errors,
        "review_required": True
    }

    report_folder = ROOT / "content"

    report_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    report_path = (
        report_folder
        / "blog_manifest.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    # Never overwrite blog pages when extraction fails.
    if not posts:
        print(
            "REPORT: 0 articles exported.",
            flush=True
        )

        print(
            "No article pages were written.",
            flush=True
        )

        print(
            "Check content/blog_manifest.json",
            flush=True
        )

        return 1

    # Write successfully extracted articles.
    for post in posts:
        generate_article(post)

    generate_archive(posts)

    print("", flush=True)
    print("=" * 55, flush=True)
    print("ANALYTICS4 BLOG MIGRATION REPORT", flush=True)
    print("=" * 55, flush=True)

    print(
        "Discovered:",
        len(found),
        flush=True
    )

    print(
        "Exported:",
        len(posts),
        flush=True
    )

    print(
        "Failed:",
        len(found) - len(posts),
        flush=True
    )

    print(
        "Other warnings:",
        len([
            e for e in errors
            if e["type"] != "article"
        ]),
        flush=True
    )

    print(
        "Report:",
        "content/blog_manifest.json",
        flush=True
    )

    print(
        "Review imported content before launch.",
        flush=True
    )

    print("=" * 55, flush=True)

    # A partial import can be committed so missing
    # articles are visible in the migration report.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
