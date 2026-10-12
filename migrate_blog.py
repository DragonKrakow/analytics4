
#!/usr/bin/env python3
"""
Analytics4 multilingual blog importer.

Imports existing public blog articles into GitHub Pages.

Supports:
    Italian: Blog/it/
    English: Blog/en/
    Polish:  Blog/pl/

Preserves original article URLs:
    Blog/<slug>/

Creates:
    content/blog_manifest.json
    Blog/index.html
    Blog/it/index.html
    Blog/en/index.html
    Blog/pl/index.html

Usage:
    python migrate_blog.py --pages 12 --download-assets

Important:
    Does not invent or automatically translate articles.
"""

import argparse
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

HOSTS = {
    "analytics4.online",
    "www.analytics4.online"
}

LANGUAGES = {
    "it": "Italiano",
    "en": "English",
    "pl": "Polski"
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; Analytics4Migration/3.0)"
    )
}

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png",
    ".webp", ".gif", ".svg"
}


def fetch(session, url):
    response = session.get(
        url,
        headers=HEADERS,
        timeout=35
    )
    response.raise_for_status()
    return response


def normalize(url, base):
    absolute = urljoin(base, url)
    parsed = urlparse(absolute)

    if parsed.netloc.lower() not in HOSTS:
        return None

    if parsed.scheme not in ("http", "https"):
        return None

    return urlunparse((
        "https",
        "analytics4.online",
        parsed.path,
        "",
        "",
        ""
    ))


def discover(soup, page_url):
    found = set()

    for anchor in soup.select("a[href]"):
        url = normalize(
            anchor["href"],
            page_url
        )

        if not url:
            continue

        path = urlparse(url).path

        if re.fullmatch(
            r"/Blog/[^/]+/?",
            path,
            re.I
        ):
            slug = path.strip("/").split("/")[-1]

            if slug.lower() not in {
                "page", "category", "tag",
                "index", "it", "en", "pl"
            }:
                found.add(url.rstrip("/") + "/")

    return found


def text_size(node):
    return len(node.get_text(" ", strip=True))


def strip_noise(node):
    selectors = (
        "script, style, form, nav, footer, "
        "header, iframe, button, "
        ".wb-menu, .wb_cookie_policy, "
        '[data-plugin="Menu"], '
        '[data-plugin="Languages"], '
        ".wb_sbg"
    )

    for item in list(node.select(selectors)):
        item.decompose()

    for tag in node.find_all(True):
        for attr in list(tag.attrs):
            if (
                attr.lower().startswith("on")
                or attr.lower() in {
                    "style", "contenteditable"
                }
            ):
                del tag[attr]

    return node


def body_element(soup):
    selectors = (
        '[itemprop="articleBody"]',
        ".blog-post-content",
        ".post-content",
        ".wb_blog_post_content",
        ".wb_blog_post",
        ".wb-blog-post",
        '[data-plugin="BlogPost"]',
        "article"
    )

    for selector in selectors:
        matches = [
            element
            for element in soup.select(selector)
            if text_size(element) >= 180
        ]

        if matches:
            return max(matches, key=text_size)

    main = (
        soup.select_one('[id^="wb_main_"]')
        or soup.select_one("#wb_main")
    )

    if not main:
        return None

    blocks = main.select(
        '[data-plugin="TextArea"]'
    )

    if not blocks or not main.select_one("h1, h2"):
        return None

    result = BeautifulSoup(
        '<div class="imported-article"></div>',
        "html.parser"
    ).div

    for block in blocks:
        if text_size(block) < 2:
            continue

        for child in list(block.contents):
            result.append(
                BeautifulSoup(
                    str(child),
                    "html.parser"
                )
            )

    if text_size(result) < 180:
        return None

    return result


def detect_language(soup, title, content):
    """
    Detect language conservatively.

    Use explicit article metadata first.
    If the website uses a generic language
    setting, inspect the actual article text.
    """

    explicit = []

    for selector, attribute in (
        ('meta[property="og:locale"]', "content"),
        ('article[lang]', "lang"),
        ('[itemprop="articleBody"][lang]', "lang")
    ):
        element = soup.select_one(selector)

        if element:
            value = element.get(attribute, "")
            explicit.append(value.lower()[:2])

    for value in explicit:
        if value in LANGUAGES:
            return value

    sample = (
        title + " " + content.get_text(" ", strip=True)
    ).lower()

    tokens = re.findall(
        r"[a-ząćęłńóśźżàèéìòù]+",
        sample
    )

    token_set = set(tokens)

    markers = {
        "pl": {
            "jest", "oraz", "które", "który",
            "możesz", "dzięki", "strona",
            "firmy", "klientów", "twojej",
            "jak", "się", "nie", "dla",
            "przez", "więcej", "google"
        },
        "it": {
            "della", "delle", "degli",
            "come", "sono", "perché",
            "questo", "questa", "anche",
            "con", "che", "gli", "una",
            "nel", "dei", "per", "più"
        },
        "en": {
            "the", "with", "your",
            "this", "that", "from",
            "how", "why", "which",
            "their", "website", "and",
            "for", "you", "are"
        }
    }

    scores = {
        lang: sum(
            1 for token in tokens
            if token in words
        )
        for lang, words in markers.items()
    }

    if any(
        char in sample
        for char in "ąćęłńśźż"
    ):
        scores["pl"] += 8

    ranking = sorted(
        scores,
        key=scores.get,
        reverse=True
    )

    winner = ranking[0]
    runner_up = ranking[1]

    if (
        scores[winner] >= 3
        and scores[winner] >= scores[runner_up] + 2
    ):
        return winner

    html_lang = (
        soup.html.get("lang", "")[:2].lower()
        if soup.html else ""
    )

    if html_lang in LANGUAGES:
        return html_lang

    # Flag uncertain articles for manual review.
    return "unknown"


def download_image(session, url):
    try:
        response = fetch(session, url)

        content_type = response.headers.get(
            "content-type", ""
        ).lower()

        if not content_type.startswith("image/"):
            return None

        if len(response.content) > 12000000:
            return None

        extension = Path(
            urlparse(url).path
        ).suffix.lower()

        if extension not in IMAGE_EXTS:
            extension = ".jpg"

        filename = (
            hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest()[:20]
            + extension
        )

        destination = (
            ROOT / "assets" / "blog" / filename
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if not destination.exists():
            destination.write_bytes(
                response.content
            )

        return "../../assets/blog/" + filename

    except Exception as exc:
        print(
            "IMAGE WARNING:",
            url,
            str(exc),
            flush=True
        )
        return None


def extract(session, url, download_assets):
    response = fetch(session, url)

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    main = (
        soup.select_one('[id^="wb_main_"]')
        or soup.select_one("#wb_main")
    )

    body = body_element(soup)

    if body is None:
        raise ValueError(
            "Article body not identified safely"
        )

    heading = (
        main.select_one("h1")
        if main else None
    ) or soup.select_one("article h1, h1")

    title = (
        heading.get_text(" ", strip=True)
        if heading else ""
    )

    if len(title) < 5:
        raise ValueError("Article heading missing")

    content = BeautifulSoup(
        str(body),
        "html.parser"
    )

    strip_noise(content)

    if text_size(content) < 180:
        raise ValueError(
            "Article content too short"
        )

    language = detect_language(
        soup, title, content
    )

    slug = (
        urlparse(url)
        .path.strip("/")
        .split("/")[-1]
    )

    for link in content.select("a[href]"):
        href = link["href"]

        if href.lower().startswith(
            ("javascript:", "data:")
        ):
            del link["href"]
        else:
            link["href"] = urljoin(url, href)

    for img in content.select("img"):
        original = (
            img.get("data-src")
            or img.get("src")
            or img.get("data-original")
        )

        if not original:
            continue

        original = urljoin(url, original)

        if not original.startswith(
            ("https://", "http://")
        ):
            continue

        img["src"] = original

        if download_assets:
            local = download_image(
                session, original
            )

            if local:
                img["src"] = local

    description = soup.select_one(
        'meta[name="description"]'
    )

    published = soup.select_one(
        'meta[property="article:published_time"], '
        "time[datetime]"
    )

    date = ""

    if published:
        date = (
            published.get("content")
            or published.get("datetime")
            or ""
        )

    return {
        "slug": slug,
        "source_url": url,
        "title": title,
        "description": (
            description.get("content", "")
            if description else ""
        ),
        "date": date,
        "language": language,
        "html": str(content),
        "status": "needs_review"
    }


def language_switcher(active):
    links = []

    for code, label in LANGUAGES.items():
        selected = (
            ' aria-current="page"'
            if code == active else ""
        )

        links.append(
            f'<a href="BLOGROOT{code}/"'
            f' data-lang="{code}"'
            f'{selected}>{label}</a>'
        )

    return (
        '<div class="blog-languages">'
        + " | ".join(links)
        + "</div>"
    )


def page(
    title,
    body,
    depth,
    description="",
    lang="it"
):
    root = "../" * depth

    meta = ""

    if description:
        meta = (
            '<meta name="description" content="'
            + html.escape(
                description,
                quote=True
            )
            + '">'
        )

    switcher = language_switcher(lang).replace(
        "BLOGROOT",
        root + "Blog/"
    )

    return f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>{html.escape(title)} | Analytics 4</title>
{meta}
<link rel="stylesheet"
      href="{root}assets/blog.css">
<style>
.blog-languages {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    margin: 20px 0;
}}
.blog-languages a {{
    color: #ff8c32;
    font-weight: 600;
    text-decoration: none;
}}
.blog-languages a[aria-current="page"] {{
    text-decoration: underline;
}}
.blog-notice {{
    padding: 12px 16px;
    border-left: 3px solid #ff8c32;
    margin: 20px 0;
}}
</style>
</head>
<body>
<header>
<a class="logo" href="{root}">
Analytics <b>4</b>
</a>
<nav>
<a href="{root}">Home</a>
<a href="{root}Blog/">Blog</a>
<a href="mailto:stefano@analytics4.online">
Contact
</a>
</nav>
</header>
<main>
{switcher}
{body}
</main>
<footer>© Analytics 4</footer>
</body>
</html>"""


def create_article(post):
    slug = post["slug"]
    language = post["language"]

    destination = (
        ROOT / "Blog" / slug / "index.html"
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    back = (
        '<p class="eyebrow">'
        '<a href="../">← Blog</a>'
        '</p>'
    )

    body = (
        back
        + "<article>"
        + "<h1>"
        + html.escape(post["title"])
        + "</h1>"
        + post["html"]
        + "</article>"
    )

    # For uncertain language, avoid declaring
    # the article as a verified translation.
    page_lang = (
        language
        if language in LANGUAGES
        else "und"
    )

    destination.write_text(
        page(
            post["title"],
            body,
            2,
            post["description"],
            page_lang
        ),
        encoding="utf-8"
    )


def create_archive(posts, language=None):
    if language:
        selected = [
            post for post in posts
            if post["language"] == language
        ]

        destination = (
            ROOT / "Blog" / language / "index.html"
        )

        heading = (
            "Blog — " + LANGUAGES[language]
        )

        depth = 2
    else:
        selected = posts

        destination = (
            ROOT / "Blog" / "index.html"
        )

        heading = "Blog & Insights"
        depth = 1

    selected.sort(
        key=lambda post: post.get("date", ""),
        reverse=True
    )

    cards = []

    for post in selected:
        slug = post["slug"]

        # Relative link to the preserved
        # original article path.
        href = (
            "../" + slug + "/"
            if language else slug + "/"
        )

        title = html.escape(post["title"])

        description = html.escape(
            post.get("description", "")[:220]
        )

        date = html.escape(
            post.get("date", "")[:10]
        )

        cards.append(
            '<a class="post" href="'
            + html.escape(href, quote=True)
            + '">'
            + "<h2>" + title + "</h2>"
            + "<small>" + date + "</small>"
            + "<p>" + description + "</p>"
            + "</a>"
        )

    if not cards:
        cards.append(
            '<p class="blog-notice">'
            'No verified articles are available '
            'in this language yet.'
            '</p>'
        )

    archive = (
        "<h1>" + html.escape(heading) + "</h1>"
        + '<section class="posts">'
        + "".join(cards)
        + "</section>"
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    destination.write_text(
        page(
            heading,
            archive,
            depth,
            lang=language or "it"
        ),
        encoding="utf-8"
    )


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
        "Discovering Analytics4 blog articles...",
        flush=True
    )

    for number in range(
        1, args.pages + 1
    ):
        if number == 1:
            candidates = [
                BASE + "Blog/"
            ]
        else:
            candidates = [
                BASE + f"Blog/?bpage={number}",
                BASE + (
                    f"Blog/?bcpp=4&bpage={number}"
                )
            ]

        for url in candidates:
            try:
                response = fetch(session, url)

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
                    "error": str(exc)
                })

            time.sleep(args.delay)

    print(
        "Discovered:",
        len(found),
        flush=True
    )

    posts = []

    for url in sorted(found):
        try:
            post = extract(
                session,
                url,
                args.download_assets
            )

            posts.append(post)

            print(
                "IMPORTED:",
                post["language"],
                post["title"],
                flush=True
            )

        except Exception as exc:
            errors.append({
                "url": url,
                "error": str(exc)
            })

            print(
                "REVIEW REQUIRED:",
                url,
                str(exc),
                flush=True
            )

        time.sleep(args.delay)

    if not posts:
        print(
            "No articles imported. "
            "Existing blog pages were not replaced.",
            flush=True
        )
        return 1

    report = {
        "source": BASE + "Blog/",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "discovered": len(found),
        "exported": len(posts),
        "failed_articles": len([
            error for error in errors
            if "/Blog/" in error["url"]
            and "bpage=" not in error["url"]
        ]),
        "languages": {
            code: sum(
                post["language"] == code
                for post in posts
            )
            for code in LANGUAGES
        },
        "unknown_language": sum(
            post["language"] == "unknown"
            for post in posts
        ),
        "posts": posts,
        "errors": errors
    }

    content_dir = ROOT / "content"

    content_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    manifest = (
        content_dir / "blog_manifest.json"
    )

    manifest.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    for post in posts:
        create_article(post)

    create_archive(posts)

    for code in LANGUAGES:
        create_archive(posts, code)

    print("")
    print("MULTILINGUAL IMPORT REPORT")
    print("--------------------------")

    print(
        "Discovered:",
        len(found)
    )

    print(
        "Imported:",
        len(posts)
    )

    for code, label in LANGUAGES.items():
        print(
            label + ":",
            report["languages"][code]
        )

    print(
        "Unknown language:",
        report["unknown_language"]
    )

    print(
        "Errors:",
        len(errors)
    )

    print(
        "Manifest:",
        manifest
    )

    print(
        "Article URLs preserved."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
