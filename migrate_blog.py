
#!/usr/bin/env python3
"""Migrate public Analytics4 SitePro blog pages into a static GitHub Pages blog.

Never invent article bodies. Export only pages with a plausible article heading and
substantial content; write a review report for anything that cannot be imported.
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

BASE = 'https://analytics4.online/'
ROOT = Path(__file__).resolve().parent  # This file is at repository root.
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; Analytics4Migration/2.0)'}
VALID_HOSTS = {'analytics4.online', 'www.analytics4.online'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}


def fetch(session, url):
    response = session.get(url, headers=HEADERS, timeout=35)
    response.raise_for_status()
    return response


def normalize(url, base):
    parsed = urlparse(urljoin(base, url))
    if parsed.netloc.lower() not in VALID_HOSTS or parsed.scheme not in ('http', 'https'):
        return None
    return urlunparse(('https', 'analytics4.online', parsed.path, '', '', ''))


def discover(soup, page_url):
    urls = set()
    for anchor in soup.select('a[href]'):
        url = normalize(anchor['href'], page_url)
        if not url:
            continue
        path = urlparse(url).path
        if re.fullmatch(r'/Blog/[^/]+/?', path, flags=re.I):
            slug = path.strip('/').split('/')[-1]
            if slug.lower() not in {'page', 'category', 'tag', 'index'}:
                urls.add(url.rstrip('/') + '/')
    return urls


def strip_noise(node):
    for item in list(node.select('script, style, form, nav, footer, header, iframe, button, '
                                 '.wb-menu, .wb_cookie_policy, [data-plugin="Menu"], '
                                 '[data-plugin="Languages"], .wb_sbg')):
        item.decompose()
    for tag in node.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith('on') or attr.lower() in {'style', 'contenteditable'}:
                del tag[attr]
    return node


def text_size(node):
    return len(node.get_text(' ', strip=True))


def body_element(soup):
    # Standard blog structures take priority when present.
    for selector in ('[itemprop="articleBody"]', '.blog-post-content', '.post-content',
                     '.wb_blog_post_content', '.wb_blog_post', '.wb-blog-post',
                     '[data-plugin="BlogPost"]', 'article'):
        matches = [x for x in soup.select(selector) if text_size(x) >= 180]
        if matches:
            return max(matches, key=text_size)

    # SitePro often stores articles as a sequence of TextArea widgets in wb_main.
    main = soup.select_one('[id^="wb_main_"]') or soup.select_one('#wb_main')
    if not main:
        return None
    blocks = main.select('[data-plugin="TextArea"]')
    # Reject a landing page accidentally mistaken for an article.
    if not blocks or not main.select_one('h1, h2'):
        return None
    result = BeautifulSoup('<div class="imported-article"></div>', 'html.parser').div
    for block in blocks:
        if text_size(block) < 2:
            continue
        # Keep only authored rich text, not the SitePro layout wrappers.
        for child in list(block.contents):
            result.append(BeautifulSoup(str(child), 'html.parser'))
    if text_size(result) < 180:
        return None
    return result


def extract(session, url, download_images):
    response = fetch(session, url)
    soup = BeautifulSoup(response.text, 'html.parser')
    main = soup.select_one('[id^="wb_main_"]') or soup.select_one('#wb_main')
    body = body_element(soup)
    if body is None:
        raise ValueError('Article body not identified safely; requires manual review')
    heading = (main.select_one('h1') if main else None) or soup.select_one('article h1, h1')
    title = heading.get_text(' ', strip=True) if heading else ''
    if not title or len(title) < 5:
        raise ValueError('Article heading missing; requires manual review')
    content = BeautifulSoup(str(body), 'html.parser')
    strip_noise(content)
    if text_size(content) < 180:
        raise ValueError('Article content too short after cleanup')
    slug = urlparse(url).path.strip('/').split('/')[-1]
    for link in content.select('a[href]'):
        href = link['href']
        if href.lower().startswith(('javascript:', 'data:')):
            del link['href']
        else:
            link['href'] = urljoin(url, href)
    for img in content.select('img'):
        original = img.get('data-src') or img.get('src') or img.get('data-original')
        if not original:
            continue
        original = urljoin(url, original)
        if not original.startswith(('https://', 'http://')):
            continue
        img['src'] = original
        if download_images:
            try:
                res = fetch(session, original)
                extension = Path(urlparse(original).path).suffix.lower()
                if extension not in IMAGE_EXTS:
                    extension = '.jpg'
                filename = hashlib.sha256(original.encode()).hexdigest()[:20] + extension
                target = ROOT / 'assets' / 'blog' / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(res.content)
                img['src'] = '../../assets/blog/' + filename
            except Exception as exc:
                print('IMAGE WARNING', original, str(exc), flush=True)
    description = soup.select_one('meta[name="description"]')
    published = soup.select_one('meta[property="article:published_time"], time[datetime]')
    date = (published.get('content') or published.get('datetime') or '') if published else ''
    lang = (soup.html.get('lang', '') if soup.html else '') or 'it'
    return {'slug': slug, 'source_url': url, 'title': title,
            'description': description.get('content', '') if description else '',
            'date': date, 'language': lang, 'html': str(content), 'status': 'needs_review'}


def page(title, body, depth, description='', lang='it'):
    root = '../' * depth
    meta = f'<meta name="description" content="{html.escape(description, quote=True)}">' if description else ''
    # Staging pages must not be indexed until original URL migration is complete.
    return (f'<!doctype html><html lang="{html.escape(lang, quote=True)}"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,follow">'
            f'<title>{html.escape(title)} | Analytics 4</title>{meta}'
            f'<link rel="stylesheet" href="{root}assets/blog.css"></head><body>'
            f'<header><a class="logo" href="{root}">Analytics <b>4</b></a>'
            f'<nav><a href="{root}">Home</a><a href="{root}Blog/">Blog</a>'
            '<a href="mailto:stefano@analytics4.online">Contact</a></nav></header>'
            f'<main>{body}</main><footer>© Analytics 4</footer></body></html>')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=12)
    parser.add_argument('--delay', type=float, default=0.8)
    parser.add_argument('--download-assets', action='store_true')
    args = parser.parse_args()
    session = requests.Session()
    found, errors = set(), []
    for number in range(1, args.pages + 1):
        candidates = ([BASE + 'Blog/'] if number == 1 else
                      [BASE + f'Blog/?bpage={number}', BASE + f'Blog/?bcpp=4&bpage={number}'])
        for url in candidates:
            try:
                found.update(discover(BeautifulSoup(fetch(session, url).text, 'html.parser'), url))
            except Exception as exc:
                errors.append({'url': url, 'error': str(exc)})
            time.sleep(args.delay)
    print('Discovered article URLs:', len(found), flush=True)
    posts = []
    for url in sorted(found):
        try:
            posts.append(extract(session, url, args.download_assets))
            print('EXTRACTED', url, flush=True)
        except Exception as exc:
            errors.append({'url': url, 'error': str(exc)})
            print('REVIEW REQUIRED', url, str(exc), flush=True)
        time.sleep(args.delay)

    report = {'source': BASE + 'Blog/', 'generated_at': datetime.now(timezone.utc).isoformat(),
              'discovered': len(found), 'exported': len(posts), 'posts': posts, 'errors': errors}
    (ROOT / 'content').mkdir(parents=True, exist_ok=True)
    (ROOT / 'content' / 'blog_manifest.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'REPORT: {len(posts)}/{len(found)} articles exported; {len(errors)} errors', flush=True)
    if not posts:
        print('No article pages written. Check content/blog_manifest.json.', flush=True)
        return 1

    for post in posts:
        dest = ROOT / 'Blog' / post['slug'] / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = (f'<p class="eyebrow"><a href="../">← Blog</a></p>'
                f'<article><h1>{html.escape(post["title"])}</h1>{post["html"]}</article>')
        dest.write_text(page(post['title'], body, 2, post['description'], post['language']), encoding='utf-8')
    cards = ''.join(f'<a class="post" href="{html.escape(p["slug"] + "/", quote=True)}">'
                    f'<h2>{html.escape(p["title"])}</h2>'
                    f'<p>{html.escape(p["description"][:200])}</p></a>' for p in posts)
    archive = ('<h1>Blog & Insights</h1><p>Articoli e approfondimenti di Analytics 4</p>'
               '<section class="posts">' + cards + '</section>')
    (ROOT / 'Blog').mkdir(parents=True, exist_ok=True)
    (ROOT / 'Blog' / 'index.html').write_text(page('Blog', archive, 1), encoding='utf-8')
    print('Generated Blog/ pages. All articles require manual review before launch.', flush=True)
    # Exit successfully when at least one article was exported, allowing the workflow
    # to commit the partial results and manifest. Missing articles remain in the report.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
