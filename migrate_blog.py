
#!/usr/bin/env python3
"""
Analytics4 multilingual SitePro blog importer.

Imports existing Italian, English and Polish articles.

Usage:
    python migrate_blog.py --pages 12 --download-assets

Outputs:
    content/blog_manifest.json
    content/blog_languages.json
    Blog/<slug>/index.html
    Blog/en/<slug>/index.html
    Blog/pl/<slug>/index.html
    Blog/it/index.html
    Blog/en/index.html
    Blog/pl/index.html

Preserves the existing Blog/index.html archive.
Does not automatically translate articles.
"""

import argparse
import hashlib
import html
import json
import re
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import (
    urljoin,
    urlparse,
    unquote
)

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
BASE = "https://analytics4.online"

LANGS = {
    "it": "Italiano",
    "en": "English",
    "pl": "Polski"
}

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; Analytics4Importer/5.0)"
    )
})

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png",
    ".webp", ".gif", ".svg"
}


# --------------------------------------------------
# HTTP
# --------------------------------------------------

def get(url):
    response = SESSION.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    return BeautifulSoup(
        response.text,
        "html.parser"
    )


def clean_url(url, base):
    absolute = urljoin(base, url)
    parsed = urlparse(absolute)

    if parsed.hostname not in (
        "analytics4.online",
        "www.analytics4.online"
    ):
        return None

    return BASE + parsed.path


# --------------------------------------------------
# ARTICLE DISCOVERY
# --------------------------------------------------

def article_slug(url):
    parts = [
        part
        for part in urlparse(url).path.split("/")
        if part
    ]

    if (
        len(parts) == 2
        and parts[0].lower() == "blog"
    ):
        slug = parts[1]

    elif (
        len(parts) == 3
        and parts[0] in ("en", "pl")
        and parts[1].lower() == "blog"
    ):
        slug = parts[2]

    else:
        return None

    excluded = {
        "blog",
        "google-ads",
        "referenze",
        "index",
        "it",
        "en",
        "pl"
    }

    if slug.lower() in excluded:
        return None

    if not re.fullmatch(
        r"[a-zA-Z0-9_-]+",
        slug
    ):
        return None

    return slug


def discover(soup, url):
    found = set()

    for anchor in soup.select("a[href]"):
        target = clean_url(
            anchor["href"],
            url
        )

        if not target:
            continue

        slug = article_slug(target)

        if slug:
            found.add(
                BASE + "/Blog/" + slug + "/"
            )

    return found


# --------------------------------------------------
# IMAGE DOWNLOAD
# --------------------------------------------------

def image_candidates(url):
    """
    SitePro commonly uses root-level image folders:

        /gallery/
        /gallery_gen/

    Some article HTML contains relative paths
    that incorrectly resolve beneath /Blog/<slug>/.
    """

    if not url:
        return []

    parsed = urlparse(url)
    path = unquote(parsed.path)

    candidates = []

    for folder in (
        "gallery_gen/",
        "gallery/"
    ):
        if folder in path:
            suffix = path.split(
                folder, 1
            )[1]

            candidates.append(
                BASE + "/" + folder + suffix
            )

    candidates.append(url)

    return list(
        dict.fromkeys(candidates)
    )


def image_download(url):
    """
    Download an image using corrected SitePro URLs.

    Returns a repository-root-relative path:
        assets/blog/filename.jpg
    """

    if not url:
        return None

    for candidate in image_candidates(url):
        try:
            response = SESSION.get(
                candidate,
                timeout=25
            )

            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "content-type", ""
                )
                .split(";")[0]
                .lower()
            )

            if not content_type.startswith(
                "image/"
            ):
                continue

            if len(response.content) > 12_000_000:
                continue

            extension = Path(
                urlparse(candidate).path
            ).suffix.lower()

            if extension not in IMAGE_EXTENSIONS:
                if "webp" in content_type:
                    extension = ".webp"
                elif "png" in content_type:
                    extension = ".png"
                elif "gif" in content_type:
                    extension = ".gif"
                else:
                    extension = ".jpg"

            filename = (
                hashlib.sha256(
                    candidate.encode("utf-8")
                ).hexdigest()[:20]
                + extension
            )

            destination = (
                ROOT
                / "assets"
                / "blog"
                / filename
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            if not destination.exists():
                destination.write_bytes(
                    response.content
                )

            return (
                "assets/blog/" + filename
            )

        except requests.RequestException:
            continue

    print(
        "IMAGE NOT FOUND:",
        url,
        flush=True
    )

    return None


# --------------------------------------------------
# ARTICLE EXTRACTION
# --------------------------------------------------

def extract(soup, url, lang, download):
    blog = soup.select_one(".wb-blog")

    if not blog:
        raise ValueError(
            "SitePro .wb-blog element missing"
        )

    schema = blog.select_one(
        '[itemtype*="BlogPosting"]'
    )

    content = None

    if schema:
        for sibling in schema.find_next_siblings():
            if (
                sibling.select_one("h1, h2")
                and len(
                    sibling.get_text(
                        " ", strip=True
                    )
                ) >= 120
            ):
                content = sibling
                break

    if content is None:
        candidates = [
            element
            for element in blog.find_all("div")
            if element.select_one("h1, h2")
            and len(
                element.get_text(
                    " ", strip=True
                )
            ) >= 180
        ]

        if candidates:
            content = min(
                candidates,
                key=lambda element: len(
                    str(element)
                )
            )

    if content is None:
        raise ValueError(
            "SitePro article content not found"
        )

    content = BeautifulSoup(
        str(content),
        "html.parser"
    )

    for node in content.select(
        "script, style, iframe, "
        "form, nav, button"
    ):
        node.decompose()

    if len(
        content.get_text(
            " ", strip=True
        )
    ) < 120:
        raise ValueError(
            "Article content too short"
        )

    heading = content.select_one("h1")

    title = (
        heading.get_text(
            " ", strip=True
        )
        if heading else ""
    )

    if not title:
        meta = soup.select_one(
            'meta[itemprop="headline"]'
        )

        if meta:
            title = meta.get(
                "content", ""
            )

    if not title:
        title_tag = soup.select_one("title")

        if title_tag:
            title = title_tag.get_text(
                " ", strip=True
            )

    if not title:
        raise ValueError(
            "Article title missing"
        )

    description_meta = soup.select_one(
        'meta[name="description"]'
    )

    description = (
        description_meta.get(
            "content", ""
        )
        if description_meta else ""
    )

    date_meta = blog.select_one(
        'meta[itemprop="datePublished"]'
    )

    date = (
        date_meta.get(
            "content", ""
        )
        if date_meta else ""
    )

    image_meta = (
        blog.select_one(
            'link[itemprop="image"]'
        )
        or soup.select_one(
            'meta[property="og:image"]'
        )
    )

    cover_url = ""

    if image_meta:
        cover_url = (
            image_meta.get("href")
            or image_meta.get("content")
            or ""
        )

    if cover_url:
        cover_url = urljoin(
            BASE + "/",
            cover_url
        )

    cover = ""

    if download and cover_url:
        cover = (
            image_download(cover_url)
            or ""
        )

    # Convert links to absolute source URLs.
    for anchor in content.select("a[href]"):
        href = anchor["href"]

        if href.lower().startswith(
            ("javascript:", "data:")
        ):
            del anchor["href"]

        else:
            anchor["href"] = urljoin(
                BASE + "/",
                href
            )

    # Download inline article images.
    for img in content.select("img"):
        raw = (
            img.get("data-src")
            or img.get("src")
            or img.get("data-original")
        )

        if not raw:
            continue

        absolute = urljoin(
            BASE + "/",
            raw
        )

        local = (
            image_download(absolute)
            if download
            else None
        )

        img["src"] = (
            local
            if local
            else absolute
        )

        for attribute in (
            "srcset",
            "data-src",
            "data-original",
            "data-lazy-src"
        ):
            img.attrs.pop(
                attribute,
                None
            )

    return {
        "slug": article_slug(url),
        "source_url": url,
        "language": lang,
        "title": title,
        "description": description,
        "date": date,
        "image": cover,
        "html": str(content)
    }


# --------------------------------------------------
# PAGE TEMPLATES
# --------------------------------------------------

def layout(title, body, lang, depth):
    root = "../" * depth

    links = " ".join(
        (
            '<a href="'
            + root
            + "Blog/"
            + code
            + '/"'
            + (
                ' aria-current="page"'
                if lang == code
                else ""
            )
            + ">"
            + label
            + "</a>"
        )
        for code, label in LANGS.items()
    )

    return f"""<!doctype html>
<html lang="{html.escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>{html.escape(title)} | Analytics4</title>

<style>
* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    background: #0b0b0d;
    color: #eeeeee;
    font-family: Arial, sans-serif;
    line-height: 1.7;
}}

header {{
    padding: 20px 5%;
    border-bottom: 1px solid #333;
}}

main {{
    max-width: 940px;
    margin: 40px auto;
    padding: 0 22px;
}}

a {{
    color: #ff963c;
}}

.lang {{
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
    margin: 24px 0;
}}

.lang [aria-current] {{
    font-weight: bold;
    text-decoration: underline;
}}

.post {{
    display: block;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 20px;
    margin: 18px 0;
    text-decoration: none;
    color: inherit;
}}

.post:hover {{
    border-color: #ff963c;
}}

.post img {{
    max-width: 200px;
    width: 35%;
    height: auto;
    float: right;
    margin-left: 20px;
}}

article img {{
    max-width: 100%;
    height: auto;
}}

article {{
    overflow-wrap: anywhere;
}}

article h1 {{
    line-height: 1.2;
}}

@media (max-width: 600px) {{
    .post img {{
        float: none;
        width: 100%;
        max-width: 100%;
        margin: 0 0 15px;
    }}
}}
</style>
</head>

<body>
<header>
<a href="{root}">Analytics4</a>
&nbsp;·&nbsp;
<a href="{root}Blog/">Blog</a>
</header>

<main>
<nav class="lang">
{links}
</nav>

{body}
</main>
</body>
</html>"""


def write(path, text):
    destination = ROOT / path

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    destination.write_text(
        text,
        encoding="utf-8"
    )


def article_html(post, lang, translated):
    slug = post["slug"]

    depth = (
        2 if lang == "it"
        else 3
    )

    root = "../" * depth

    language_links = []

    for code, label in LANGS.items():
        if code in translated:
            if code == "it":
                target = (
                    root
                    + "Blog/"
                    + slug
                    + "/"
                )
            else:
                target = (
                    root
                    + "Blog/"
                    + code
                    + "/"
                    + slug
                    + "/"
                )
        else:
            target = (
                root
                + "Blog/"
                + code
                + "/"
            )

        language_links.append(
            '<a href="'
            + target
            + '">'
            + label
            + "</a>"
        )

    cover = post.get(
        "image", ""
    )

    cover_html = ""

    if cover:
        cover_html = (
            '<img alt="" src="'
            + root
            + html.escape(
                cover,
                quote=True
            )
            + '">'
        )

    article_content = BeautifulSoup(
        post.get("html", ""),
        "html.parser"
    )

    for img in article_content.select("img"):
        src = img.get("src", "")

        if src.startswith("assets/blog/"):
            img["src"] = root + src

    body = (
        '<nav class="lang">'
        + " · ".join(language_links)
        + "</nav>"
        + "<article>"
        + "<h1>"
        + html.escape(post["title"])
        + "</h1>"
        + cover_html
        + str(article_content)
        + "</article>"
    )

    return layout(
        post["title"],
        body,
        lang,
        depth
    )


def archive(posts, lang, depth):
    cards = []

    sorted_posts = sorted(
        posts,
        key=lambda post: post.get(
            "date", ""
        ),
        reverse=True
    )

    for post in sorted_posts:
        slug = post["slug"]

        href = (
            "../" + slug + "/"
            if lang == "it"
            else slug + "/"
        )

        cover = post.get(
            "image", ""
        )

        picture = ""

        if cover:
            prefix = "../" * depth

            picture = (
                '<img alt="" src="'
                + prefix
                + html.escape(
                    cover,
                    quote=True
                )
                + '">'
            )

        cards.append(
            '<a class="post" href="'
            + href
            + '">'
            + picture
            + "<h2>"
            + html.escape(
                post["title"]
            )
            + "</h2>"
            + "<p>"
            + html.escape(
                post.get(
                    "description", ""
                )[:250]
            )
            + "</p>"
            + '<div style="clear:both"></div>'
            + "</a>"
        )

    if cards:
        listing = "".join(cards)
    else:
        listing = (
            "<p>No articles available "
            "in this language yet.</p>"
        )

    body = (
        "<h1>Blog & Insights</h1>"
        + listing
    )

    return layout(
        "Blog & Insights",
        body,
        lang,
        depth
    )


# --------------------------------------------------
# MAIN IMPORT
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--pages",
        type=int,
        default=12
    )

    parser.add_argument(
        "--download-assets",
        action="store_true"
    )

    args = parser.parse_args()

    found = set()
    errors = []

    print(
        "Discovering original blog...",
        flush=True
    )

    for page_number in range(
        1,
        args.pages + 1
    ):
        if page_number == 1:
            urls = [
                BASE + "/Blog/"
            ]
        else:
            urls = [
                (
                    BASE
                    + "/Blog/?bpage="
                    + str(page_number)
                ),
                (
                    BASE
                    + "/Blog/?bcpp=4&bpage="
                    + str(page_number)
                )
            ]

        for url in urls:
            try:
                soup = get(url)

                found.update(
                    discover(
                        soup,
                        url
                    )
                )

            except requests.RequestException as exc:
                errors.append({
                    "url": url,
                    "error": str(exc)
                })

    print(
        "Discovered candidates:",
        len(found),
        flush=True
    )

    manifest_path = (
        ROOT
        / "content"
        / "blog_manifest.json"
    )

    old_manifest = {}

    if manifest_path.exists():
        old_manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )

    old_posts = {
        post["slug"]: post
        for post in old_manifest.get(
            "posts", []
        )
        if post.get("slug")
    }

    imported = {}

    for original_url in sorted(found):
        slug = article_slug(
            original_url
        )

        if not slug:
            continue

        versions = {}

        for lang in LANGS:
            if lang == "it":
                url = (
                    BASE
                    + "/Blog/"
                    + slug
                    + "/"
                )
            else:
                url = (
                    BASE
                    + "/"
                    + lang
                    + "/Blog/"
                    + slug
                    + "/"
                )

            try:
                soup = get(url)

                page_lang = (
                    soup.html.get(
                        "lang", ""
                    ).lower()[:2]
                    if soup.html
                    else ""
                )

                if page_lang != lang:
                    print(
                        "SKIP LANGUAGE MISMATCH:",
                        lang,
                        slug,
                        page_lang,
                        flush=True
                    )
                    continue

                post = extract(
                    soup,
                    url,
                    lang,
                    args.download_assets
                )

                versions[lang] = post

                print(
                    "IMPORTED:",
                    lang,
                    slug,
                    flush=True
                )

            except Exception as exc:
                print(
                    "SKIP:",
                    lang,
                    slug,
                    str(exc),
                    flush=True
                )

                errors.append({
                    "url": url,
                    "error": str(exc)
                })

        if versions:
            imported[slug] = versions

    if not imported:
        print(
            "No articles imported. "
            "Existing blog left untouched.",
            flush=True
        )

        return 1

    # Save translated article pages.
    for slug, versions in imported.items():
        for lang, post in versions.items():
            if lang == "it":
                path = (
                    "Blog/"
                    + slug
                    + "/index.html"
                )
            else:
                path = (
                    "Blog/"
                    + lang
                    + "/"
                    + slug
                    + "/index.html"
                )

            write(
                path,
                article_html(
                    post,
                    lang,
                    versions
                )
            )

    # Keep existing Italian manifest compatibility.
    manifest_posts = []

    for slug, versions in imported.items():
        if "it" in versions:
            manifest_posts.append(
                versions["it"]
            )

        elif slug in old_posts:
            manifest_posts.append(
                old_posts[slug]
            )

    known_slugs = {
        post["slug"]
        for post in manifest_posts
    }

    for slug, post in old_posts.items():
        if slug not in known_slugs:
            manifest_posts.append(post)

    # Separate multilingual article feeds.
    feeds = {
        lang: [
            versions[lang]
            for versions in imported.values()
            if lang in versions
        ]
        for lang in LANGS
    }

    manifest = {
        "source": BASE + "/Blog/",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "discovered": len(found),
        "exported": len(manifest_posts),
        "failed_articles": len(errors),
        "languages": {
            lang: len(feeds[lang])
            for lang in LANGS
        },
        "posts": manifest_posts,
        "errors": errors
    }

    write(
        "content/blog_manifest.json",
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2
        )
    )

    write(
        "content/blog_languages.json",
        json.dumps(
            feeds,
            ensure_ascii=False,
            indent=2
        )
    )

    # Generate language-specific archives.
    for lang, posts in feeds.items():
        write(
            (
                "Blog/"
                + lang
                + "/index.html"
            ),
            archive(
                posts,
                lang,
                2
            )
        )

    # Preserve the existing main blog archive.
    root_archive = (
        ROOT
        / "Blog"
        / "index.html"
    )

    if not root_archive.exists():
        write(
            "Blog/index.html",
            archive(
                manifest_posts,
                "it",
                1
            )
        )

    print("")
    print("IMPORT SUMMARY")
    print("-------------------------")

    for lang, label in LANGS.items():
        print(
            label + ":",
            len(feeds[lang])
        )

    print(
        "Italian manifest articles:",
        len(manifest_posts)
    )

    print(
        "Total language versions:",
        sum(
            len(posts)
            for posts in feeds.values()
        )
    )

    print(
        "Errors:",
        len(errors)
    )

    print(
        "Import complete.",
        flush=True
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
