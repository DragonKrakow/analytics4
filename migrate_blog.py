#!/usr/bin/env python3
"""Import publicly accessible Analytics4 blog articles as static pages.
No files are written when no articles can be extracted. Review output before publishing.
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

BASE = 'https://analytics4.online/'
ROOT = Path(__file__).resolve().parents[1]
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; Analytics4SiteMigration/1.0)'}

def fetch(session, url):
    response = session.get(url, headers=HEADERS, timeout=35)
    response.raise_for_status()
    return response

def discover(soup, page_url):
    urls = set()
    for anchor in soup.select('a[href]'):
        url = urljoin(page_url, anchor['href']).split('#')[0].split('?')[0]
        parsed = urlparse(url)
        if parsed.netloc.lower() not in {'analytics4.online', 'www.analytics4.online'}:
            continue
        if re.match(r'^/Blog/[^/]+/?$', parsed.path, re.I):
            slug = parsed.path.strip('/').split('/')[-1]
            if slug.lower() not in {'page', 'category', 'tag'}:
                urls.add(url.rstrip('/') + '/')
    return urls

def body_element(soup):
    selectors = ['[itemprop="articleBody"]', '.blog-post-content', '.post-content',
                 '[data-plugin="BlogPost"]', '.wb_blog_post', '.blog-post', 'article']
    for selector in selectors:
        matches = [x for x in soup.select(selector) if len(x.get_text(' ', strip=True)) >= 180]
        if matches:
            return max(matches, key=lambda x: len(x.get_text(' ', strip=True)))
    # Site-builder markup fallback: choose a substantial content section, not the full page.
    for selector in ['.wb_blog_post_content', '.wb-blog-post', '[class*="blog-post"]']:
        matches = [x for x in soup.select(selector) if len(x.get_text(' ', strip=True)) >= 180]
        if matches:
            return max(matches, key=lambda x: len(x.get_text(' ', strip=True)))
    return None

def extract(session, url, download_images):
    soup = BeautifulSoup(fetch(session, url).text, 'html.parser')
    body = body_element(soup)
    if body is None:
        raise ValueError('Article body not identified safely; requires manual review')
    title_tag = soup.select_one('article h1, .blog-post h1, h1')
    title = title_tag.get_text(' ', strip=True) if title_tag else (soup.title.get_text(' ', strip=True) if soup.title else url)
    content = BeautifulSoup(str(body), 'html.parser')
    for node in content.select('script, style, form, nav, footer, header, iframe, button'):
        node.decompose()
    for node in content.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith('on'):
                del node[attr]
    for link in content.select('a[href]'):
        link['href'] = urljoin(url, link['href'])
    slug = urlparse(url).path.strip('/').split('/')[-1]
    for img in content.select('img'):
        original = img.get('src') or img.get('data-src') or img.get('data-original')
        if not original:
            continue
        original = urljoin(url, original)
        img['src'] = original
        if download_images:
            try:
                res = fetch(session, original)
                ext = Path(urlparse(original).path).suffix.lower()
                if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}:
                    ext = '.jpg'
                name = hashlib.sha256(original.encode()).hexdigest()[:20] + ext
                folder = ROOT / 'assets' / 'blog'
                folder.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(res.content)
                img['src'] = '../../assets/blog/' + name
            except Exception as exc:
                print('IMAGE WARNING', original, str(exc))
    description = soup.select_one('meta[name="description"]')
    published = soup.select_one('meta[property="article:published_time"], time[datetime]')
    language = (soup.html.get('lang', '') if soup.html else '') or 'it'
    return {'slug': slug, 'source_url': url, 'title': title,
            'description': description.get('content', '') if description else '',
            'date': (published.get('content') or published.get('datetime') or '') if published else '',
            'language': language, 'html': str(content), 'status': 'needs_review'}

def page(title, body, depth, description='', lang='it', canonical=None):
    root = '../' * depth
    meta = f'<meta name="description" content="{html.escape(description, quote=True)}">' if description else ''
    canon = f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">' if canonical else ''
    return (f'<!doctype html><html lang="{html.escape(lang, quote=True)}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)} | Analytics 4</title>{meta}{canon}'
            f'<link rel="stylesheet" href="{root}assets/blog.css"></head><body>'
            f'<header><a class="logo" href="{root}">Analytics <b>4</b></a>'
            f'<nav><a href="{root}">Home</a><a href="{root}Blog/">Blog</a>'
            f'<a href="mailto:stefano@analytics4.online">Contact</a></nav></header>'
            f'<main>{body}</main><footer>© Analytics 4 · '
            f'<a href="mailto:stefano@analytics4.online">Contact</a></footer></body></html>')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=12)
    parser.add_argument('--delay', type=float, default=0.8)
    parser.add_argument('--download-assets', action='store_true')
    args = parser.parse_args()
    session = requests.Session()
    found, errors = set(), []
    # Try common SitePro archive pagination conventions; deduplicate resulting URLs.
    for number in range(1, args.pages + 1):
        candidates = ([BASE + 'Blog/'] if number == 1 else [
            BASE + f'Blog/?bpage={number}',
            BASE + f'Blog/?bcpp=4&bpage={number}',
        ])
        for url in candidates:
            try:
                found.update(discover(BeautifulSoup(fetch(session, url).text, 'html.parser'), url))
            except Exception as exc:
                errors.append({'url': url, 'error': str(exc)})
            time.sleep(args.delay)
    print('Discovered unique article URLs:', len(found))
    if not found:
        raise SystemExit('No articles found. Existing output preserved; inspect blog archive markup.')
    posts = []
    for url in sorted(found):
        try:
            post = extract(session, url, args.download_assets)
            posts.append(post)
            print('EXTRACTED', url)
        except Exception as exc:
            errors.append({'url': url, 'error': str(exc)})
            print('REVIEW REQUIRED', url, exc)
        time.sleep(args.delay)
    if not posts:
        raise SystemExit('No article bodies extracted. Existing output preserved.')
    for post in posts:
        dest = ROOT / 'Blog' / post['slug'] / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = (f'<p class="eyebrow"><a href="../">← Blog</a></p>'
                f'<article><h1>{html.escape(post["title"])}</h1>{post["html"]}</article>')
        dest.write_text(page(post['title'], body, 2, post['description'], post['language'], post['source_url']), encoding='utf-8')
    cards = ''.join(f'<a class="post" href="{html.escape(p["slug"] + "/", quote=True)}">'
                    f'<h2>{html.escape(p["title"])}</h2>'
                    f'<p>{html.escape(p["description"][:200])}</p></a>' for p in posts)
    archive = '<h1>Blog & Insights</h1><p>Articoli e approfondimenti di Analytics 4</p><section class="posts">' + cards + '</section>'
    (ROOT / 'Blog').mkdir(exist_ok=True)
    (ROOT / 'Blog' / 'index.html').write_text(page('Blog', archive, 1), encoding='utf-8')
    (ROOT / 'content').mkdir(exist_ok=True)
    manifest = {'source': BASE + 'Blog/', 'generated_at': datetime.now(timezone.utc).isoformat(),
                'discovered': len(found), 'exported': len(posts), 'posts': posts, 'errors': errors}
    (ROOT / 'content' / 'blog_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Exported {len(posts)} of {len(found)}. Review content/blog_manifest.json and rendered pages.')
    if len(posts) < len(found):
        raise SystemExit(2)

if __name__ == '__main__':
    main()
