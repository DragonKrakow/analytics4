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
                cover = image.get('content', '') if image else ''
                if not cover:
                    first = article.find('img')
                    cover = first.get('src', '') if first else ''
                published = soup.find('meta', attrs={'property': 'article:published_time'})
                records[lang].setdefault(slug, {})
                records[lang][slug].update({
                    'slug': slug,
                    'title': title,
                    'description': desc.get('content', '') if desc else '',
                    'date': published.get('content', '') if published else records[lang][slug].get('date', ''),
                    'image': cover,
                    'html': str(article),
                })
            except OSError as exc:
                print(f'WARNING: Cannot read {page.relative_to(ROOT)}: {exc}')
    return records


def find_article_content(soup):
    return soup.find('article')


def normalise_asset(value):
    """Return a repository-relative assets/blog/... path when possible."""
    value = str(value or '')
    match = re.search(r'(?:^|/)(assets/blog/[^?#]+)', unquote(urlparse(value).path))
    return match.group(1) if match else image_path(value)


def bootstrap():
    sources = get_source_records()
    total = 0
    for lang in LANGS:
        folder = POSTS / lang
        folder.mkdir(parents=True, exist_ok=True)
        for slug, source in sorted(sources[lang].items()):
            target = folder / f'{slug}.md'
            html = source.get('html')
            if target.exists() or not html:
                continue
            soup = BeautifulSoup(html, 'html.parser')
            body = soup.find('article') or soup
            for h1 in body.find_all('h1'):
                h1.decompose()
            cover = normalise_asset(source.get('image'))
            first = body.find('img')
            if first is not None and not cover:
                cover = normalise_asset(first.get('src'))
            if first is not None and normalise_asset(first.get('src')) == cover:
                first.decompose()
            for img in body.select('img[src]'):
                src = normalise_asset(img['src'])
                if src.startswith('assets/blog/'):
                    img['src'] = '/analytics4/' + src
            text = to_md(str(body), heading_style='ATX').strip()
            front = {
                'title': source.get('title') or slug.replace('-', ' '),
                'description': source.get('description', ''),
                'date': clean_date(source.get('date')),
                'image': '/analytics4/' + cover if cover.startswith('assets/blog/') else cover,
                'published': True,
            }
            target.write_text(
                '---\n' + yaml.safe_dump(front, allow_unicode=True, sort_keys=False) + '---\n\n' + text + '\n',
                encoding='utf-8')
            total += 1
    print(f'Imported {total} existing article versions. Existing CMS files preserved.')


def parse_post(path, lang):
    raw = path.read_text(encoding='utf-8')
    parts = raw.split('---', 2) if raw.startswith('---') else []
    if len(parts) < 3:
        raise ValueError(f'Missing frontmatter: {path}')
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict):
        raise ValueError(f'Invalid frontmatter: {path}')
    slug = path.stem
    if not safe_slug(slug):
        raise ValueError(f'Invalid article filename: {path.name}')
    body = markdown.markdown(parts[2].strip(), extensions=['extra', 'sane_lists'])
    soup = BeautifulSoup(body, 'html.parser')
    for img in soup.select('img[src]'):
        img['src'] = normalise_asset(img['src'])
    return {
        'slug': slug,
        'title': str(meta.get('title') or slug.replace('-', ' ')),
        'description': str(meta.get('description') or ''),
        'date': clean_date(meta.get('date')),
        'image': normalise_asset(meta.get('image')),
        'html': str(soup),
        'language': lang,
        'published': meta.get('published', True) is not False,
    }


def write_json(path, data):
    legacy.write(path, json.dumps(data, ensure_ascii=False, indent=2))


def build():
    feeds = {lang: [] for lang in LANGS}
    for lang in LANGS:
        for path in sorted((POSTS / lang).glob('*.md')):
            post = parse_post(path, lang)
            if post['published']:
                feeds[lang].append(post)
        feeds[lang].sort(key=lambda p: p['date'], reverse=True)
    versions = {}
    for lang, posts in feeds.items():
        for post in posts:
            versions.setdefault(post['slug'], {})[lang] = post

    outputs = set()
    for slug, langs in versions.items():
        for lang, post in langs.items():
            rel = (f'Blog/{slug}/index.html' if lang == 'it'
                   else f'Blog/{lang}/{slug}/index.html')
            legacy.write(rel, legacy.article_html(post, lang, langs))
            outputs.add(rel)
    for lang, posts in feeds.items():
        rel = f'Blog/{lang}/index.html'
        legacy.write(rel, legacy.archive(posts, lang, 2))
        outputs.add(rel)

    old = read_json(STATE, [])
    old = old if isinstance(old, list) else []
    root_archive = ROOT / 'Blog' / 'index.html'
    if not root_archive.exists() or 'Blog/index.html' in old:
        legacy.write('Blog/index.html', legacy.archive(feeds['it'], 'it', 1))
        outputs.add('Blog/index.html')

    cards = {
        lang: [{
            'slug': p['slug'], 'title': p['title'], 'description': p['description'],
            'date': p['date'], 'image': p['image'], 'language': lang,
            'url': (f'Blog/{p["slug"]}/' if lang == 'it' else f'Blog/{lang}/{p["slug"]}/'),
        } for p in posts]
        for lang, posts in feeds.items()
    }
    for lang in LANGS:
        write_json(f'content/blog_cards_{lang}.json', cards[lang])
    write_json('content/blog_cards.json', cards['it'])
    write_json('content/blog_cards_multilingual.json', cards)
    write_json('content/blog_languages.json', {
        lang: [{k: v for k, v in p.items() if k != 'published'} for p in posts]
        for lang, posts in feeds.items()})
    write_json('content/blog_manifest.json', {
        'posts': [{k: v for k, v in p.items() if k != 'published'} for p in feeds['it']],
        'exported': len(feeds['it']),
        'discovered': sum(len(p) for p in feeds.values()),
        'failed_articles': 0,
    })

    for rel in old:
        target = (ROOT / str(rel)).resolve()
        if (rel not in outputs and target.is_relative_to((ROOT / 'Blog').resolve())
                and target.is_file()):
            target.unlink()
            if target.parent != (ROOT / 'Blog').resolve() and not any(target.parent.iterdir()):
                target.parent.rmdir()
    write_json('content/cms_generated_paths.json', sorted(outputs))

    print('Published article counts:')
    for lang in LANGS:
        print(f'  {lang}: {len(feeds[lang])}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('bootstrap', 'build'))
    args = parser.parse_args()
    {'bootstrap': bootstrap, 'build': build}[args.command]()


if __name__ == '__main__':
    main()
