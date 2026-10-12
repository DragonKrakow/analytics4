
#!/usr/bin/env python3
"""Analytics4 multilingual blog image repair and card builder."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
BASE = "https://analytics4.online"
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets" / "blog"

LANGS = ("it", "en", "pl")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 Analytics4BlogMedia/3.0"
})

EXTENSIONS = (
    ".jpg", ".jpeg", ".png",
    ".webp", ".gif", ".svg"
)


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def candidates(value, source=""):
    if not value:
        return []

    if value.startswith(("data:", "javascript:", "#")):
        return []

    if value.startswith("assets/blog/"):
        return []

    if value.startswith(("../assets/blog/", "../../assets/blog/",
                         "../../../assets/blog/")):
        return []

    result = []

    absolute = urljoin(source or BASE + "/", value)
    parsed = urlparse(absolute)
    path = unquote(parsed.path)

    # SitePro gallery URLs are normally root-relative.
    for folder in ("gallery_gen/", "gallery/"):
        if folder in path:
            suffix = path.split(folder, 1)[1]
            result.append(BASE + "/" + folder + suffix)

    result.append(absolute)

    return list(dict.fromkeys(result))


def download(url):
    ASSETS.mkdir(parents=True, exist_ok=True)

    for candidate in candidates(url):
        try:
            response = SESSION.get(candidate, timeout=25)
            response.raise_for_status()

            content_type = response.headers.get(
                "content-type", ""
            ).split(";")[0].lower()

            if not content_type.startswith("image/"):
                continue

            if len(response.content) > 12_000_000:
                continue

            ext = Path(urlparse(candidate).path).suffix.lower()

            if ext not in EXTENSIONS:
                if "webp" in content_type:
                    ext = ".webp"
                elif "png" in content_type:
                    ext = ".png"
                elif "gif" in content_type:
                    ext = ".gif"
                else:
                    ext = ".jpg"

            name = (
                hashlib.sha256(candidate.encode()).hexdigest()[:20]
                + ext
            )

            destination = ASSETS / name

            if not destination.exists():
                destination.write_bytes(response.content)

            return "assets/blog/" + name

        except requests.RequestException:
            continue

    return None


def local_asset(value):
    if not value:
        return None

    match = re.search(
        r"assets/blog/([a-zA-Z0-9_.-]+)",
        value
    )

    if not match:
        return None

    path = "assets/blog/" + match.group(1)

    if (ROOT / path).is_file():
        return path

    return None


def image_sources(img, source):
    values = []

    for attr in (
        "data-src", "data-original",
        "data-lazy-src", "src"
    ):
        if img.get(attr):
            values.append(img[attr])

    if img.get("srcset"):
        values.extend(
            item.strip().split()[0]
            for item in img["srcset"].split(",")
            if item.strip()
        )

    result = []

    for value in values:
        result.extend(candidates(value, source))

    return list(dict.fromkeys(result))


def repair_article(post, lang):
    slug = post.get("slug", "")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        return None

    if lang == "it":
        article = ROOT / "Blog" / slug / "index.html"
        prefix = "../../"
        url = "Blog/" + slug + "/"
    else:
        article = ROOT / "Blog" / lang / slug / "index.html"
        prefix = "../../../"
        url = "Blog/" + lang + "/" + slug + "/"

    if not article.exists():
        print("MISSING ARTICLE:", lang, slug)
        return None

    soup = BeautifulSoup(
        article.read_text(encoding="utf-8"),
        "html.parser"
    )

    source = post.get("source_url", "")
    original = BeautifulSoup(
        post.get("html", ""),
        "html.parser"
    )

    images = soup.select("article img")
    original_images = original.select("img")

    cover = local_asset(post.get("image", ""))

    # Repair article images, keeping existing working files.
    for index, img in enumerate(images):
        current = img.get("src", "")
        path = local_asset(current)

        if not path:
            sources = []

            if index < len(original_images):
                sources.extend(
                    image_sources(original_images[index], source)
                )

            sources.extend(image_sources(img, source))

            for candidate in dict.fromkeys(sources):
                path = download(candidate)
                if path:
                    break

        if path:
            img["src"] = prefix + path

            for attr in (
                "srcset", "data-src",
                "data-original", "data-lazy-src"
            ):
                img.attrs.pop(attr, None)

            if not cover:
                cover = path

    # Recover featured image from original article metadata.
    if not cover:
        sources = []

        for value in (
            post.get("image", ""),
            post.get("cover", "")
        ):
            sources.extend(candidates(value, source))

        try:
            if source:
                response = SESSION.get(source, timeout=25)

                if response.ok:
                    remote = BeautifulSoup(
                        response.text, "html.parser"
                    )

                    for selector, attribute in (
                        ('meta[property="og:image"]', "content"),
                        ('link[itemprop="image"]', "href"),
                        ('meta[itemprop="image"]', "content")
                    ):
                        node = remote.select_one(selector)

                        if node and node.get(attribute):
                            sources.extend(
                                candidates(node[attribute], source)
                            )

                    for img in remote.select(
                        ".wb-blog img, article img"
                    )[:8]:
                        sources.extend(image_sources(img, source))

        except requests.RequestException as exc:
            print("SOURCE WARNING:", source, str(exc))

        for candidate in dict.fromkeys(sources):
            cover = download(candidate)
            if cover:
                break

    # Update the featured image in the article if it already exists.
    if cover:
        first = soup.select_one("article > img")

        if first:
            first["src"] = prefix + cover

    article.write_text(str(soup), encoding="utf-8")

    return {
        "slug": slug,
        "title": post.get("title", ""),
        "description": post.get("description", ""),
        "date": post.get("date", ""),
        "image": cover or "",
        "url": url,
        "language": lang
    }


def repair_archive(path, cards, prefix):
    if not path.exists():
        return

    soup = BeautifulSoup(
        path.read_text(encoding="utf-8"),
        "html.parser"
    )

    by_slug = {
        card["slug"]: card
        for card in cards
    }

    changed = False

    for anchor in soup.select("a[href]"):
        href = urlparse(anchor.get("href", "")).path
        slug = href.rstrip("/").split("/")[-1]

        card = by_slug.get(slug)

        if not card:
            continue

        img = anchor.select_one("img")

        if not img:
            continue

        cover = card.get("image", "")

        if cover:
            new_src = prefix + cover

            if img.get("src") != new_src:
                img["src"] = new_src
                changed = True

            for attr in (
                "srcset", "data-src",
                "data-original", "data-lazy-src"
            ):
                if attr in img.attrs:
                    del img[attr]
                    changed = True

    if changed:
        path.write_text(str(soup), encoding="utf-8")


def main():
    manifest_path = CONTENT / "blog_manifest.json"
    languages_path = CONTENT / "blog_languages.json"

    if not manifest_path.exists():
        raise SystemExit(
            "Missing content/blog_manifest.json"
        )

    manifest = load_json(manifest_path, {})
    language_data = load_json(languages_path, {})

    # Italian manifest is retained for compatibility.
    italian_posts = manifest.get("posts", [])

    feeds = {}

    for lang in LANGS:
        if lang == "it":
            posts = language_data.get("it", [])

            # Include older Italian articles retained by importer.
            known = {
                p.get("slug")
                for p in posts
            }

            posts = posts + [
                p for p in italian_posts
                if p.get("slug") not in known
            ]
        else:
            posts = language_data.get(lang, [])

        cards = []

        for post in posts:
            result = repair_article(post, lang)

            if result:
                cards.append(result)

        cards.sort(
            key=lambda x: x.get("date", ""),
            reverse=True
        )

        feeds[lang] = cards

        save_json(
            CONTENT / ("blog_cards_" + lang + ".json"),
            cards
        )

        print(
            lang.upper(),
            "articles:", len(cards),
            "with images:",
            sum(bool(p["image"]) for p in cards)
        )

    # Existing homepage reads blog_cards.json.
    # Keep this file compatible with that homepage.
    save_json(
        CONTENT / "blog_cards.json",
        feeds["it"]
    )

    # Multilingual feed for the next homepage update.
    save_json(
        CONTENT / "blog_cards_multilingual.json",
        feeds
    )

    # Repair archive images without replacing their layout.
    repair_archive(
        ROOT / "Blog" / "index.html",
        feeds["it"],
        "../"
    )

    for lang in LANGS:
        repair_archive(
            ROOT / "Blog" / lang / "index.html",
            feeds[lang],
            "../../"
        )

    print("")
    print("BLOG MEDIA REPAIR COMPLETE")

    for lang in LANGS:
        print(
            lang,
            len(feeds[lang]),
            "cards"
        )


if __name__ == "__main__":
    main()
