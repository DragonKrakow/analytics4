
#!/usr/bin/env python3
"""
Analytics4 blog media repair.

Reads:
    content/blog_manifest.json

Repairs:
    Blog/<slug>/index.html
    Blog/index.html

Creates:
    content/blog_cards.json

Requires:
    requests
    beautifulsoup4
"""

import hashlib
import json
import mimetypes
import re

from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "content" / "blog_manifest.json"
OUT = ROOT / "content" / "blog_cards.json"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = (
    "Mozilla/5.0 (compatible; Analytics4Blog/1.0)"
)

EXTS = {
    ".jpg", ".jpeg", ".png",
    ".webp", ".gif", ".svg"
}


def download(url):
    """Download a real image into assets/blog."""

    try:
        response = SESSION.get(url, timeout=25)
        response.raise_for_status()

        content_type = response.headers.get(
            "content-type", ""
        ).split(";")[0].lower()

        if not content_type.startswith("image/"):
            return None

        if len(response.content) > 12_000_000:
            return None

        extension = Path(
            urlparse(url).path
        ).suffix.lower()

        if extension not in EXTS:
            extension = (
                mimetypes.guess_extension(content_type)
                or ".jpg"
            )

        if extension == ".jpe":
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

        return "assets/blog/" + filename

    except Exception as exc:
        print(
            "IMAGE WARNING:",
            url,
            str(exc),
            flush=True
        )
        return None


def candidate_urls(node, base):
    """Find possible image URLs."""

    if node is None:
        return []

    values = []

    for key in (
        "data-src",
        "data-original",
        "data-lazy-src",
        "src"
    ):
        if node.get(key):
            values.append(node[key])

    if node.get("srcset"):
        values.extend(
            item.strip().split(" ")[0]
            for item in node["srcset"].split(",")
        )

    return [
        urljoin(base, value)
        for value in values
        if value and not value.startswith("data:")
    ]


def main():

    if not MANIFEST.exists():
        raise SystemExit(
            "Missing content/blog_manifest.json. "
            "Run the blog importer first."
        )

    data = json.loads(
        MANIFEST.read_text(encoding="utf-8")
    )

    cards = []

    for post in data.get("posts", []):

        slug = post.get("slug", "")
        source = post.get("source_url", "")

        if not re.fullmatch(r"[\w-]+", slug):
            continue

        article = (
            ROOT / "Blog" / slug / "index.html"
        )

        if not article.exists():
            print(
                "ARTICLE MISSING:",
                slug,
                flush=True
            )
            continue

        print(
            "Processing:",
            slug,
            flush=True
        )

        soup = BeautifulSoup(
            article.read_text(encoding="utf-8"),
            "html.parser"
        )

        original = BeautifulSoup(
            post.get("html", ""),
            "html.parser"
        )

        original_imgs = original.select("img")
        page_imgs = soup.select("article img")

        remote_soup = None

        try:
            if source:
                response = SESSION.get(
                    source,
                    timeout=25
                )

                if response.ok:
                    remote_soup = BeautifulSoup(
                        response.text,
                        "html.parser"
                    )

        except Exception as exc:
            print(
                "SOURCE WARNING:",
                source,
                str(exc),
                flush=True
            )

        remote_imgs = []

        if remote_soup:
            remote_imgs = remote_soup.select(
                'article img, '
                '[itemprop="articleBody"] img, '
                '[id^="wb_main_"] img'
            )

        cover = None

        # Repair images inside article pages.
        for i, img in enumerate(page_imgs):

            existing = img.get("src", "")

            local_path = None

            if existing.startswith(
                "../../assets/blog/"
            ):
                relative = existing[6:]

                if (ROOT / relative).exists():
                    local_path = relative

            if not local_path:

                candidates = []

                if i < len(original_imgs):
                    candidates += candidate_urls(
                        original_imgs[i],
                        source
                    )

                if i < len(remote_imgs):
                    candidates += candidate_urls(
                        remote_imgs[i],
                        source
                    )

                candidates += candidate_urls(
                    img,
                    source
                )

                for url in dict.fromkeys(candidates):

                    if not url.startswith("http"):
                        continue

                    local_path = download(url)

                    if local_path:
                        break

            if local_path:

                img["src"] = "../../" + local_path

                for attr in (
                    "srcset",
                    "data-src",
                    "data-original",
                    "data-lazy-src"
                ):
                    img.attrs.pop(attr, None)

                if cover is None:
                    cover = local_path

        # Recover the article's featured image.
        if not cover and remote_soup:

            meta = remote_soup.select_one(
                'meta[property="og:image"], '
                'meta[name="twitter:image"]'
            )

            candidates = []

            if meta and meta.get("content"):
                candidates.append(
                    urljoin(
                        source,
                        meta["content"]
                    )
                )

            for image in remote_imgs[:6]:
                candidates += candidate_urls(
                    image,
                    source
                )

            for url in dict.fromkeys(candidates):

                cover = download(url)

                if cover:
                    break

        article.write_text(
            str(soup),
            encoding="utf-8"
        )

        cards.append({
            "slug": slug,
            "title": post.get("title", ""),
            "description": post.get(
                "description", ""
            ),
            "date": post.get("date", ""),
            "image": cover or "",
            "url": "Blog/" + slug + "/"
        })

    # Save data for homepage article cards.
    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUT.write_text(
        json.dumps(
            cards,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    # Repair images in the Blog archive.
    archive = ROOT / "Blog" / "index.html"

    if archive.exists():

        soup = BeautifulSoup(
            archive.read_text(encoding="utf-8"),
            "html.parser"
        )

        byslug = {
            card["slug"]: card
            for card in cards
        }

        for anchor in soup.select("a[href]"):

            slug = urlparse(
                anchor["href"]
            ).path.strip("/").split("/")[-1]

            item = byslug.get(slug)

            if not item:
                continue

            image = anchor.select_one("img")

            if image:

                if item["image"]:

                    image["src"] = (
                        "../" + item["image"]
                    )

                    for attr in (
                        "srcset",
                        "data-src",
                        "data-original",
                        "data-lazy-src"
                    ):
                        image.attrs.pop(attr, None)

                else:
                    image.decompose()

        archive.write_text(
            str(soup),
            encoding="utf-8"
        )

    print("")
    print("BLOG MEDIA REPORT")
    print("-----------------")
    print("Blog cards:", len(cards))
    print(
        "Articles with images:",
        sum(
            bool(card["image"])
            for card in cards
        )
    )
    print(
        "Output:",
        "content/blog_cards.json"
    )


if __name__ == "__main__":
    main()
