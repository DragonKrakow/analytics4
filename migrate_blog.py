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
                      if x.select_one('h1, h2') and len(x.get_text(' ', strip=True)) >= 180]
        if candidates:
            content = min(candidates, key=lambda x: len(str(x)))
    if content is None:
        raise ValueError('SitePro article content not found')
    content = BeautifulSoup(str(content), 'html.parser')
    for node in content.select('script, style, iframe, form, nav, button'):
        node.decompose()
    if len(content.get_text(' ', strip=True)) < 120:
        raise ValueError('Article content too short')
    heading = content.select_one('h1')
    title = heading.get_text(' ', strip=True) if heading else ''
    if not title:
        meta = soup.select_one('meta[itemprop="headline"]')
        title = meta.get('content', '') if meta else ''
    if not title:
        raise ValueError('Article title missing')
    meta_desc = soup.select_one('meta[name="description"]')
    description = meta_desc.get('content', '') if meta_desc else ''
    date_meta = blog.select_one('meta[itemprop="datePublished"]')
    date = date_meta.get('content', '') if date_meta else ''
    image_meta = blog.select_one('link[itemprop="image"]') or soup.select_one('meta[property="og:image"]')
    cover_url = image_meta.get('href') or image_meta.get('content') if image_meta else ''
    cover_url = urljoin(url, cover_url) if cover_url else ''
    cover = image_download(cover_url) if download and cover_url else ''
    for a in content.select('a[href]'):
        if a['href'].lower().startswith(('javascript:', 'data:')):
            del a['href']
        else:
            a['href'] = urljoin(url, a['href'])
    for img in content.select('img'):
        raw = img.get('data-src') or img.get('src') or img.get('data-original')
        if not raw:
            continue
        absolute = urljoin(url, raw)
        local = image_download(absolute) if download else None
        img['src'] = ('../../' + local) if local else absolute
        for attr in ('srcset', 'data-src', 'data-original', 'data-lazy-src'):
            img.attrs.pop(attr, None)
    return dict(slug=article_slug(url), source_url=url, language=lang,
                title=title, description=description, date=date,
                image=cover or '', html=str(content))


def layout(title, body, lang, depth):
    root = '../' * depth
    links = ' '.join('<a href="' + root + 'Blog/' + code + '/"' +
                     (' aria-current="page"' if lang == code else '') + '>' + label + '</a>'
                     for code, label in LANGS.items())
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>{html.escape(title)} | Analytics4</title>
<link rel="stylesheet" href="{root}blog.css">
<style>body{{background:#0b0b0d;color:#eee;font-family:Arial,sans-serif;line-height:1.7}}
main{{max-width:940px;margin:40px auto;padding:0 22px}}a{{color:#ff963c}}
header{{padding:20px 5%;border-bottom:1px solid #333}}
.lang{{display:flex;gap:18px;margin:24px 0}}.lang [aria-current]{{font-weight:bold;text-decoration:underline}}
.post{{display:block;border:1px solid #333;border-radius:12px;padding:20px;margin:18px 0;text-decoration:none}}
.post img{{max-width:200px;width:35%;float:right;margin-left:20px}}
article img{{max-width:100%;height:auto}}article{{overflow-wrap:anywhere}}</style></head>
<body><header><a href="{root}">Analytics4</a> · <a href="{root}Blog/">Blog</a></header>
<main><nav class="lang">{links}</nav>{body}</main></body></html>'''


def write(path, text):
    dest = ROOT / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding='utf-8')


def article_html(post, lang, translated):
    root = '../../' if lang == 'it' else '../../../'
    links = []
    for code, label in LANGS.items():
        target = (root + 'Blog/' + ('' if code == 'it' else code + '/') + post['slug'] + '/')
        if code not in translated:
            target = root + 'Blog/' + code + '/'
        links.append('<a href="' + target + '">' + label + '</a>')
    cover = post.get('image', '')
    if cover:
        cover = '<img alt="" src="' + root + html.escape(cover, quote=True) + '">'
    body = ('<nav class="lang">' + ' · '.join(links) + '</nav><article>' +
            '<h1>' + html.escape(post['title']) + '</h1>' + cover + post['html'] + '</article>')
    return layout(post['title'], body, lang, 2 if lang == 'it' else 3)


def archive(posts, lang, depth):
    cards = []
    for post in sorted(posts, key=lambda p: p.get('date', ''), reverse=True):
        slug = post['slug']
        href = slug + '/'
        cover = post.get('image', '')
        pic = '<img alt="" src="' + ('../../' if lang else '../') + html.escape(cover, quote=True) + '">' if cover else ''
        cards.append('<a class="post" href="' + href + '">' + pic + '<h2>' +
                     html.escape(post['title']) + '</h2><p>' +
                     html.escape(post.get('description', '')[:250]) + '</p><div style="clear:both"></div></a>')
    body = '<h1>Blog & Insights</h1>' + (''.join(cards) if cards else '<p>No articles available in this language yet.</p>')
    return layout('Blog & Insights', body, lang or 'it', depth)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=12)
    parser.add_argument('--download-assets', action='store_true')
    args = parser.parse_args()
    found = set()
    errors = []
    for page in range(1, args.pages + 1):
        urls = [BASE + '/Blog/'] if page == 1 else [
            BASE + '/Blog/?bpage=' + str(page),
            BASE + '/Blog/?bcpp=4&bpage=' + str(page)]
        for url in urls:
            try:
                found.update(discover(get(url), url))
            except Exception as e:
                errors.append({'url': url, 'error': str(e)})
    print('Discovered candidates:', len(found), flush=True)
    existing = ROOT / 'content' / 'blog_manifest.json'
    old = json.loads(existing.read_text(encoding='utf-8')) if existing.exists() else {}
    old_posts = {p['slug']: p for p in old.get('posts', []) if p.get('slug')}
    imported = {}
    for original in sorted(found):
        slug = article_slug(original)
        versions = {}
        for lang in LANGS:
            url = BASE + ('/' + lang if lang != 'it' else '') + '/Blog/' + slug + '/'
            try:
                soup = get(url)
                # Verify that SitePro actually serves this language, rather than redirecting
                # to an Italian fallback page.
                page_lang = (soup.html.get('lang', '') if soup.html else '').lower()[:2]
                if page_lang != lang:
                    print('SKIP language mismatch:', lang, url, 'html=', page_lang, flush=True)
                    continue
                post = extract(soup, url, lang, args.download_assets)
                versions[lang] = post
                print('IMPORTED:', lang, slug, flush=True)
            except Exception as e:
                print('SKIP:', lang, slug, str(e), flush=True)
                errors.append({'url': url, 'error': str(e)})
        if versions:
            imported[slug] = versions
    # Do not overwrite working articles if the original site stops responding.
    if not imported:
        print('No new articles. Existing blog untouched.', flush=True)
        return 1
    # Keep existing imported articles that were not found this time.
    for slug, versions in imported.items():
        for lang, post in versions.items():
            path = ('Blog/' + slug + '/index.html' if lang == 'it' else
                    'Blog/' + lang + '/' + slug + '/index.html')
            write(path, article_html(post, lang, versions))
    # Build manifest with the Italian version for compatibility with build_blog_media.py.
    manifest_posts = []
    for slug, versions in imported.items():
        if 'it' in versions:
            manifest_posts.append(versions['it'])
        elif slug in old_posts:
            manifest_posts.append(old_posts[slug])
    for slug, post in old_posts.items():
        if slug not in {p['slug'] for p in manifest_posts}:
            manifest_posts.append(post)
    manifest = dict(source=BASE + '/Blog/', generated_at=datetime.now(timezone.utc).isoformat(),
                    discovered=len(found), exported=len(manifest_posts),
                    failed_articles=len(errors), posts=manifest_posts, errors=errors,
                    languages={lang: sum(lang in versions for versions in imported.values()) for lang in LANGS})
    write('content/blog_manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False))
    # Separate language feeds for future homepage integration.
    feeds = {lang: [post for versions in imported.values() for code, post in versions.items() if code == lang]
             for lang in LANGS}
    write('content/blog_languages.json', json.dumps(feeds, indent=2, ensure_ascii=False))
    for lang, posts in feeds.items():
        write('Blog/' + lang + '/index.html', archive(posts, lang, 2))
    # Keep existing root archive if present to avoid breaking its established design.
    if not (ROOT / 'Blog' / 'index.html').exists():
        write('Blog/index.html', archive(manifest_posts, None, 1))
    print('IMPORT SUMMARY:', manifest['languages'], 'manifest:', len(manifest_posts), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
