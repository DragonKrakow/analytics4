#!/usr/bin/env python3
"""Analytics4 SitePro multilingual blog importer (IT/EN/PL).
Run: python migrate_blog.py --pages 12 --download-assets
Preserves existing pages on failures; imports only genuine available translations.
"""
import argparse
import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
BASE = 'https://analytics4.online'
LANGS = {'it': 'Italiano', 'en': 'English', 'pl': 'Polski'}
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'Mozilla/5.0 (compatible; Analytics4Importer/4.0)'


def get(url):
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, 'html.parser')


def clean_url(url, base):
    absolute = urljoin(base, url)
    parsed = urlparse(absolute)
    if parsed.hostname not in ('analytics4.online', 'www.analytics4.online'):
        return None
    return BASE + parsed.path


def article_slug(url):
    parts = [x for x in urlparse(url).path.split('/') if x]
    if len(parts) == 2 and parts[0].lower() == 'blog':
        slug = parts[1]
    elif len(parts) == 3 and parts[0] in ('en', 'pl') and parts[1].lower() == 'blog':
        slug = parts[2]
    else:
        return None
    if slug.lower() in ('blog', 'google-ads', 'referenze', 'index', 'it', 'en', 'pl'):
        return None
    return slug if re.fullmatch(r'[a-zA-Z0-9_-]+', slug) else None


def discover(soup, url):
    found = set()
    for a in soup.select('a[href]'):
        target = clean_url(a['href'], url)
        if target and article_slug(target):
            found.add(BASE + '/Blog/' + article_slug(target) + '/')
    return found


def image_download(url):
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        content_type = r.headers.get('content-type', '').lower()
        if not content_type.startswith('image/') or len(r.content) > 12000000:
            return None
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'):
            ext = '.png' if 'png' in content_type else '.jpg'
        name = hashlib.sha256(url.encode()).hexdigest()[:20] + ext
        dest = ROOT / 'assets' / 'blog' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(r.content)
        return 'assets/blog/' + name
    except Exception as e:
        print('IMAGE WARNING:', url, str(e), flush=True)
        return None


def extract(soup, url, lang, download):
    blog = soup.select_one('.wb-blog')
    if not blog:
        raise ValueError('SitePro .wb-blog element missing')
    # SitePro stores the actual article after its BlogPosting schema element.
    schema = blog.select_one('[itemtype*="BlogPosting"]')
    content = None
    if schema:
        for sibling in schema.find_next_siblings():
            if sibling.select_one('h1, h2') and len(sibling.get_text(' ', strip=True)) >= 120:
                content = sibling
                break
    if content is None:
        candidates = [x for x in blog.find_all('div')
