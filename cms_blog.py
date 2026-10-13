#!/usr/bin/env python3
"""Analytics4 blog CMS: recover legacy articles into Markdown, then publish CMS posts.

bootstrap: imports available article HTML into content/posts/<language>/*.md.
           Never overwrites existing Markdown. Does not change the public site.
build:     publishes only published CMS Markdown posts. Run after reviewing bootstrap.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import markdown
import yaml
from bs4 import BeautifulSoup
from markdownify import markdownify as to_md

import migrate_blog as legacy

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / 'content'
POSTS = CONTENT / 'posts'
LANGS = ('it', 'en', 'pl')
STATE = CONTENT / 'cms_generated_paths.json'


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        print(f'WARNING: Cannot parse {path.relative_to(ROOT)}: {exc}')
        return default


def clean_date(value):
    value = str(value or '')
    return value[:10] if re.match(r'^\d{4}-\d{2}-\d{2}', value) else '2026-01-01'


def image_path(value):
    value = str(value or '')
    if value.startswith('/analytics4/assets/blog/'):
        return value.removeprefix('/analytics4/')
    if value.startswith('/assets/blog/'):
        return value.lstrip('/')
    return value


def safe_slug(value):
    return bool(re.fullmatch(r'[A-Za-z0-9_-]+', str(value or '')))


def get_source_records():
    """Use JSON metadata only to locate actual HTML; do not trust its language labels."""
    grouped = read_json(CONTENT / 'blog_languages.json', {})
    records = {lang: {} for lang in LANGS}
    for lang in LANGS:
        for item in grouped.get(lang, []) if isinstance(grouped, dict) else []:
            if isinstance(item, dict) and safe_slug(item.get('slug')):
                records[lang][item['slug']] = item
        cards = read_json(CONTENT / f'blog_cards_{lang}.json', [])
        if isinstance(cards, list):
            for item in cards:
                if isinstance(item, dict) and safe_slug(item.get('slug')):
                    # Prefer full original source, but use cards to recover missing entries.
                    records[lang].setdefault(item['slug'], item)
    # Italian compatibility feed (older imports may have no per-language cards).
    cards = read_json(CONTENT / 'blog_cards.json', [])
    if isinstance(cards, list):
        for item in cards:
            if isinstance(item, dict) and safe_slug(item.get('slug')):
                records['it'].setdefault(item['slug'], item)
    # Recover directly from published HTML when JSON feeds are empty or incomplete.
    # Archives are excluded: only Blog/<slug>/index.html (IT) and
    # Blog/<lang>/<slug>/index.html (EN/PL) are article candidates.
    for lang in LANGS:
        paths = ((ROOT / 'Blog').glob('*/index.html') if lang == 'it'
                 else (ROOT / 'Blog' / lang).glob('*/index.html'))
        for page in paths:
            slug = page.parent.name
            if not safe_slug(slug) or slug in LANGS:
                continue
            try:
                soup = BeautifulSoup(page.read_text(encoding='utf-8', errors='replace'), 'html.parser')
                article = find_article_content(soup)
                if article is None:
                    continue
                h1 = article.find('h1') or soup.find('h1')
                og = soup.find('meta', attrs={'property': 'og:title'})
                title = (h1.get_text(' ', strip=True) if h1 else
                         (og.get('content', '') if og else slug.replace('-', ' ')))
                desc = soup.find('meta', attrs={'name': 'description'})
                image = soup.find('meta', attrs={'property': 'og:image'})
